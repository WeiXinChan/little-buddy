package com.littlebuddy.v2

import android.os.Handler
import android.os.SystemClock
import android.util.Base64
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID
import java.util.concurrent.TimeUnit

/** One audio-handler owner. No body logging, file cache, retry or V1 configuration. */
internal class VoiceClient(private val handler: Handler, private val status: (String) -> Unit,
                           private val hideImage: () -> Unit, private val reveal: (String, Int) -> Unit,
                           private val failed: () -> Unit = {}, waits: Waits = Waits(),
                           private val observed: (PlaybackAck) -> Unit = {}) {
    val quarantined get() = player.quarantined
    private var socket: WebSocket? = null
    private var epoch = 0L
    private var sequence = 0L
    private var active = false
    @Volatile var isAwake = false; private set
    @Volatile var idleSerial = 0L; private set
    @Volatile var inputSerial = 0L; private set
    private var outputBusy = false
    private val gate: InputGate = InputGate(waits, SystemClock::elapsedRealtime,
        { version -> send("advance", "revision" to version); candidate() },
        { version -> send("probe", "revision" to version) },
        { version -> send("seal", "revision" to version); inputSerial++ ; outputBusy = true },
        { send("wake_solo"); outputBusy = true },
        { send("thinking_prompt", "revision" to gateVersion()); status("thinking") },
        { isAwake = false; idleSerial++; interrupt(); status("wake") })
    private fun gateVersion(): Long = gate.revision
    private var ackIdentity: JSONObject? = null
    private var ackSequence = 0L
    private var playerName: String? = null
    private val http = OkHttpClient.Builder().retryOnConnectionFailure(false)
        .followRedirects(false).connectTimeout(4, TimeUnit.SECONDS).build()
    private val player = Playback({ AndroidTrack(handler) { fail("route") } },
        SystemClock::elapsedRealtime) { ack ->
        observed(ack)
        val identity = ackIdentity ?: return@Playback
        val copy = JSONObject(identity.toString()).put("sequence", ackSequence++)
        send("ack", "identity" to copy, "player" to ack.binding.player,
             "stream" to ack.binding.stream, "segment" to ack.segment, "head" to ack.head)
    }
    private val pump = object : Runnable {
        override fun run() {
            if (!active) return
            try { player.tick(); gate.tick(outputBusy) } catch (_: Exception) { fail("playback"); return }
            handler.postDelayed(this, 10)
        }
    }
    private val heartbeat = object : Runnable {
        override fun run() {
            if (!active) return
            send("heartbeat")
            handler.postDelayed(this, 5000)
        }
    }

    fun connect(address: String, token: String) {
        check(!active && !player.quarantined)
        require(address.startsWith("wss://") && address.endsWith("/v2/voice") &&
                !address.contains('@') && !address.contains('?') && !address.contains('#'))
        require(token.matches(Regex("[a-zA-Z0-9]{32,256}")))
        active = true
        epoch = 0; sequence = 0
        val request = Request.Builder().url(address).header("Authorization", "Bearer $token").build()
        socket = http.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) { handler.post {
                if (socket !== webSocket || !active) return@post
                status("wake"); pump.run(); heartbeat.run()
            } }
            override fun onMessage(webSocket: WebSocket, text: String) { handler.post {
                if (socket !== webSocket || !active) return@post
                try { receive(text) } catch (_: Exception) { fail("protocol") }
            } }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                handler.post { if (socket === webSocket) fail("network") }
            }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                handler.post { if (socket === webSocket) fail("closed") }
            }
        })
    }
    private fun send(kind: String, vararg values: Pair<String, Any>) {
        if (!active) return
        val message = JSONObject().put("v", 2).put("type", kind).put("epoch", epoch).put("seq", sequence++)
        values.forEach { message.put(it.first, it.second) }
        val current = socket ?: return
        if (current.queueSize() > 64000 || !current.send(message.toString())) fail("backpressure")
    }
    private fun receive(text: String) {
        require(text.length <= 16000)
        val event = JSONObject(text)
        require(event.getInt("v") == 2)
        if (event.getLong("epoch") != epoch) return
        when (event.getString("type")) {
            "endpoint" -> {
                gate.decision(event.getLong("revision"), Completion.valueOf(event.getString("completion").uppercase()))
            }
            "open" -> {
                if (event.getLong("revision") != gate.revision) return
                outputBusy = true
                check(player.binding == null)
                playerName = UUID.randomUUID().toString()
                send("bind", "player" to checkNotNull(playerName))
            }
            "bound" -> {
                require(event.getString("player") == playerName)
                ackIdentity = event.getJSONObject("identity"); ackSequence = 0
                player.bind(Binding(epoch, checkNotNull(playerName), event.getInt("stream")))
            }
            "audio" -> {
                val data = Base64.decode(event.getString("pcm"), Base64.NO_WRAP)
                require(data.isNotEmpty() && data.size <= 4800 && data.size % 2 == 0)
                val pcm = ShortArray(data.size/2)
                ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(pcm)
                val binding = Binding(epoch, event.getString("player"), event.getInt("stream"))
                player.enqueue(AudioPacket(binding, event.getString("segment"), event.getLong("start"),
                                           event.getLong("end"), pcm))
                data.fill(0); status("speaking")
            }
            "decision" -> {
                if (event.getLong("revision") != gate.revision) return
                when (event.getString("meaning")) {
                "noise", "backchannel" -> {
                    if (player.suspended) player.resumeConfirmedNoise()
                    send("resume_noise"); outputBusy = player.hasPending
                }
                "thinking" -> status("listening")
                "new_turn", "stop" -> interrupt(event.optString("intent", ""))
                else -> status("clarify") // Unknown recognition never resumes audio.
            }
            }
            "revoke" -> { player.stop(); ackIdentity = null; hideImage() }
            "reveal" -> if (player.binding != null && !player.suspended)
                reveal(event.getString("effect"), event.getInt("topic"))
            "thinking_wait" -> status("thinking")
            "reply_end" -> { outputBusy = false; gate.interaction(); status("listening") }
            "failure" -> { interrupt(); status("failure") }
            else -> error("unknown event")
        }
    }
    fun input(samples: ShortArray, count: Int) {
        require(count in 1..3200)
        val bytes = ByteBuffer.allocate(count * 2).order(ByteOrder.LITTLE_ENDIAN)
        repeat(count) { bytes.putShort(samples[it]) }
        send("input", "pcm" to Base64.encodeToString(bytes.array(), Base64.NO_WRAP))
        bytes.array().fill(0)
    }
    fun wake() { isAwake = true; gate.wake(); send("wake"); status("listening") }
    fun frame(samples: ShortArray, speech: Boolean) {
        if (speech) gate.speech() else gate.quiet()
        input(samples, samples.size)
        samples.fill(0)
    }
    fun quiet() { gate.quiet() }
    fun candidate() {
        if (player.binding != null && !player.suspended) {
            player.suspendOutput(); send("suspend")
        }
    }
    fun interrupt(intent: String = "") {
        val stopped = player.stop() // First: local mute, generation revoke, flush, stop/release.
        ackIdentity = null; playerName = null; outputBusy = false
        hideImage()
        epoch++; sequence = 0
        if (!stopped.stopped || !stopped.released) { fail("release"); return }
        send("stop", "intent" to intent) // Only after local native calls completed.
    }
    private fun fail(code: String) { close(); status(code); failed() }
    fun close() {
        active = false; isAwake = false; outputBusy = false
        player.stop(); ackIdentity = null; hideImage()
        handler.removeCallbacks(pump); handler.removeCallbacks(heartbeat)
        val old = socket; socket = null
        old?.cancel()
    }
}
