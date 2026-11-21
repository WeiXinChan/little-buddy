package com.littlebuddy

import android.os.Handler
import com.littlebuddy.voice.AudioPort
import com.littlebuddy.voice.ReplyPort
import com.littlebuddy.voice.Segment
import com.littlebuddy.voice.Turn
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.TimeUnit
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
    private val segment: (Turn, Segment) -> Unit,
    private val ended: (Turn, Int) -> Unit,
) : AudioPort, ReplyPort {
    @Volatile private var active: Attempt? = null
    private var nativeCapture: Long? = null
    private val client = OkHttpClient.Builder()
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
            Request.Builder().url(url).header("Authorization", "Bearer $token").build(), attempt,
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
        val socket = checkNotNull(attempt.socket)
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

    fun close() {
        val old = active
        active = null
        old?.socket?.cancel()
    }

    private inner class Attempt(val operation: Long) : WebSocketListener() {
        @Volatile var socket: WebSocket? = null
        var position = 0
        @Volatile var turn: Turn? = null
        private var ready = false
        private var finished = false
        private var next = 1
        private var samples: ShortArray? = null
        private var received = 0

        private fun dispatch(action: () -> Unit) {
            dispatcher.post { if (active === this) action() }
        }

        fun fail() {
            socket?.cancel()
            dispatch { failed(operation, turn) }
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
                        check(turn != null && next <= 8 && samples == null && control.getInt("number") == next)
                        samples = ShortArray(240_000)
                        received = 0
                    }
                    "segment.end" -> {
                        val id = checkNotNull(turn)
                        check(control.getInt("number") == next && control.getInt("samples") == received)
                        check(received > 0)
                        val result = Segment(next++, checkNotNull(samples).copyOf(received))
                        samples = null
                        dispatch { segment(id, result) }
                    }
                    "reply.end" -> {
                        val id = checkNotNull(turn)
                        val count = control.getInt("count")
                        check(samples == null && count > 0 && count == next - 1)
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
                val target = checkNotNull(samples)
                check(bytes.size in 8..6406 && bytes.size % 2 == 0)
                val packet = ByteBuffer.wrap(bytes.toByteArray())
                check(packet.get().toInt() == 1 && packet.get().toInt() == 2 && packet.int == received)
                packet.order(ByteOrder.LITTLE_ENDIAN)
                val count = packet.remaining() / 2
                check(received + count <= target.size)
                packet.asShortBuffer().get(target, received, count)
                received += count
            } catch (_: Exception) {
                fail()
            }
        }
    }
}
