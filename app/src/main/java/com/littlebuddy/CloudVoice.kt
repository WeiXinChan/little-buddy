package com.littlebuddy

import android.os.Handler
import android.os.SystemClock
import android.util.Log
import com.littlebuddy.voice.AudioPort
import com.littlebuddy.voice.ReplyPort
import com.littlebuddy.voice.PcmStream
import com.littlebuddy.voice.Turn
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.json.JSONObject

internal class CloudVoice(
    private val dispatcher: Handler,
    private val audio: AudioPort,
    private val config: () -> Pair<String, String>,
    private val failed: (Long, Turn?) -> Unit,
    private val released: (Long) -> Unit,
    private val segment: (Turn, Int, PcmStream) -> Unit,
    private val ended: (Turn, Int) -> Unit,
) : AudioPort, ReplyPort {
    @Volatile private var active: Attempt? = null
    private var nativeCapture: Long? = null
    private val client = OkHttpClient.Builder()
        .retryOnConnectionFailure(false)
        .followRedirects(false)
        .followSslRedirects(false)
        .connectTimeout(4, TimeUnit.SECONDS)
        .pingInterval(10, TimeUnit.SECONDS)
        .build()

    override fun capture(operation: Long) {
        close()
        captureOperation = operation
        val attempt = Attempt(operation)
        active = attempt
        val (address, token) = config()
        val url = address.removePrefix("wss://").let { "https://$it".toHttpUrlOrNull() }
        if (!address.startsWith("wss://") || url == null || url.encodedPath != "/v1/turn" ||
            url.username.isNotEmpty() || url.password.isNotEmpty() || url.query != null ||
            url.fragment != null || !token.matches(Regex("[a-zA-Z0-9]{32,256}"))
        ) {
            attempt.fail()
            return
        }
        attempt.socket = client.newWebSocket(
            Request.Builder().url(url)
                .header("Authorization", "Bearer $token")
                .header("X-Voice-Turn-ID", attempt.trace.id)
                .build(), attempt,
        )
    }

    // Called by the audio worker. The dispatcher seals only after native release.
    fun upload(id: Long, samples: ShortArray, count: Int) {
        val attempt = active ?: return
        if (attempt.operation != id) return
        val size = minOf(count, 320_000 - attempt.position)
        if (size <= 0) return
        val packet = ByteBuffer.allocate(6 + 2 * size)
        packet.put(1).put(1).putInt(attempt.position).order(ByteOrder.LITTLE_ENDIAN)
        repeat(size) { packet.putShort(samples[it]) }
        val socket = attempt.socket ?: return
        if (socket.queueSize() > 64_000 || !socket.send(packet.array().toByteString())) {
            attempt.fail()
            return
        }
        attempt.position += size
    }

    override fun request(turn: Turn) {
        val attempt = checkNotNull(active)
        attempt.turn = turn
        if (attempt.socket?.send("""{"v":1,"type":"turn.end","samples":${attempt.position}}""") != true) {
            attempt.fail()
        }
    }

    fun captureStarted(id: Long) {
        active?.takeIf { it.operation == id }?.trace?.started()
    }

    fun speechDetected(id: Long) {
        active?.takeIf { it.operation == id }?.trace?.speechDetected()
    }

    fun captureSealed(id: Long) {
        active?.takeIf { it.operation == id }?.trace?.endpointConfirmed()
    }

    override fun playStream(operation: Long, stream: PcmStream) = audio.playStream(operation, stream)

    override fun play(operation: Long, samples: ShortArray) = audio.play(operation, samples)

    override fun stop(operation: Long) {
        if (nativeCapture == operation || captureOperation != operation) audio.stop(operation)
        else dispatcher.post { released(operation) }
    }

    private var captureOperation: Long? = null

    override fun discardCapture(operation: Long) {
        if (active?.operation == operation) close()
    }

    override fun cancel(turn: Turn) {
        if (active?.turn == turn) close()
    }

    override fun finished(turn: Turn) {
        if (active?.turn == turn) close(success = true)
    }

    fun close(success: Boolean = false) {
        val old = active
        active = null
        old?.terminate(success)
    }

    private inner class Attempt(val operation: Long) : WebSocketListener() {
        @Volatile var socket: WebSocket? = null
        var position = 0
        @Volatile var turn: Turn? = null
        val trace = VoiceTrace(operation, SystemClock::elapsedRealtime) { Log.d("LittleBuddyVoice", it) }
        private val terminated = AtomicBoolean()
        private val streams = ConcurrentLinkedQueue<CloudPcm>()
        private var ready = false
        private var finished = false
        private var next = 1
        private var current: CloudPcm? = null

        private fun dispatch(action: () -> Unit) {
            dispatcher.post { if (active === this && !terminated.get()) action() }
        }

        fun terminate(success: Boolean = false): Boolean {
            if (!terminated.compareAndSet(false, true)) return false
            trace.finish(success)
            streams.forEach { it.abort() }
            socket?.cancel()
            return true
        }

        fun fail() {
            if (terminate()) dispatcher.post {
                if (active === this) failed(operation, turn)
            }
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            if (!finished) fail()
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            if (!finished) fail()
            webSocket.close(1000, null)
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            try {
                if (terminated.get()) return
                check(text.length <= 256 && !finished)
                val control = JSONObject(text)
                check(control.getInt("v") == 1)
                when (control.getString("type")) {
                    "turn.ready" -> {
                        check(!ready)
                        ready = true
                        dispatch {
                            nativeCapture = operation
                            audio.capture(operation)
                        }
                    }
                    "segment.start" -> {
                        check(turn != null && next <= 8 && current == null && control.getInt("number") == next)
                        val number = next
                        val source = CloudPcm({ event, op -> trace.playback(event, op, number) })
                        streams.add(source)
                        if (terminated.get()) source.abort()
                        current = source
                    }
                    "segment.end" -> {
                        check(control.getInt("number") == next)
                        checkNotNull(current).seal(control.getInt("samples"))
                        next++
                        current = null
                    }
                    "reply.end" -> {
                        val id = checkNotNull(turn)
                        val count = control.getInt("count")
                        check(current == null && count > 0 && count == next - 1)
                        finished = true
                        dispatch { ended(id, count) }
                        webSocket.close(1000, null)
                    }
                    else -> error("Unexpected control")
                }
            } catch (_: Exception) {
                fail()
            }
        }

        override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
            try {
                if (terminated.get()) return
                check(bytes.size in 8..6406)
                val source = checkNotNull(current)
                if (source.push(bytes.toByteArray())) {
                    val id = checkNotNull(turn)
                    val number = next
                    trace.pcm(number)
                    dispatch { segment(id, number, source) }
                }
            } catch (_: Exception) {
                fail()
            }
        }
    }
}
