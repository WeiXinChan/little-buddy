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
                           private val observed: (PlaybackAck) -> Unit = {},
                           private val completed: (Long, Int) -> Unit = { _, _ -> },
                           private val allowAck: (PlaybackAck) -> Boolean = { true },
                           private val playbackSettings: com.littlebuddy.v2.parent.ParentPlaybackSettings = com.littlebuddy.v2.parent.ParentPlaybackSettings(),
                           private val localHelp: (LocalHelpReason) -> Unit = {},
                           private val management: () -> Unit = {},
                           private val permitted: () -> Boolean = { true },
                           private val images: ImagePort? = null) {
    fun nativeProof() = player.nativeProof()
    val quarantined get() = player.quarantined
    private var socket: WebSocket? = null
    private var epoch = 0L
    private var sequence = 0L
    private var active = false
    @Volatile var isAwake = false; private set
    @Volatile var idleSerial = 0L; private set
    @Volatile var inputSerial = 0L; private set
    private var outputBusy = false
    private var responseRevision = -1L
    private val gate: InputGate = InputGate(waits, SystemClock::elapsedRealtime,
        { version -> images?.clear(); send("advance", "revision" to version); candidate() },
        { version -> send("probe", "revision" to version) },
        { version -> send("seal", "revision" to version); inputSerial++ ; outputBusy = true },
        { send("wake_solo", "age_ms" to (15000L - (gateDeadline() - SystemClock.elapsedRealtime()))); outputBusy = true },
        { send("thinking_prompt", "revision" to gateVersion()); status("thinking") },
        { isAwake = false; idleSerial++; interrupt(); status("wake") })
    private fun gateDeadline(): Long = gate.responseDeadline
    private fun gateVersion(): Long = gate.revision
    private val helpScope = LocalHelpScope()
    private var ackIdentity: JSONObject? = null
    private var ackSequence = 0L
    private var playerName: String? = null
    private val http = OkHttpClient.Builder().retryOnConnectionFailure(false)
        .followRedirects(false).connectTimeout(4, TimeUnit.SECONDS).build()
    private val player = Playback({ AndroidTrack(handler, playbackSettings) { fail("route") } },
        SystemClock::elapsedRealtime) { ack ->
        observed(ack)
        if (ack.completed && responseRevision == gate.revision && ack.binding.epoch == epoch) gate.effectivePlayed()
        if (!allowAck(ack)) return@Playback
        val identity = ackIdentity ?: return@Playback
        val copy = JSONObject(identity.toString()).put("sequence", ackSequence++)
        val sent = send("ack", "identity" to copy, "player" to ack.binding.player,
             "stream" to ack.binding.stream, "segment" to ack.segment, "head" to ack.head)
        if (sent) recordImageAck(ack)
    }
    private val pump = object : Runnable {
        override fun run() {
            if (!active) return
            if (!permitted()) { fail("lifecycle"); return }
            try { gate.checkResponseDeadline(); player.tick(); gate.tick(outputBusy) } catch (_: Exception) { fail("playback"); return }
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
        check(!active && !player.quarantined && permitted())
        require(address.startsWith("wss://") && address.endsWith("/v2/voice") &&
                !address.contains('@') && !address.contains('?') && !address.contains('#'))
        require(token.matches(Regex("[a-zA-Z0-9]{32,256}")))
        active = true
        epoch = 0; sequence = 0; helpScope.clear()
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
    private fun send(kind: String, vararg values: Pair<String, Any>): Boolean {
        if (!active || !permitted()) return false
        val message = JSONObject().put("v", 2).put("type", kind).put("epoch", epoch).put("seq", sequence++)
        values.forEach { message.put(it.first, it.second) }
        val current = socket ?: return false
        if (current.queueSize() > 64000 || !current.send(message.toString())) { fail("backpressure"); return false }
        return true
    }
    private fun receive(text: String) {
        if (!permitted()) { close(); return }
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
                if (event.has("session") && event.has("turn"))
                    helpScope.bind(event.getString("session"), event.getLong("turn"), epoch, gate.revision)
                outputBusy = true
                responseRevision = gate.revision
                check(player.binding == null)
                playerName = UUID.randomUUID().toString()
                if (images != null) send("bind", "player" to checkNotNull(playerName), "features" to org.json.JSONArray().put("images_v1"))
                else send("bind", "player" to checkNotNull(playerName))
            }
            "bound" -> {
                require(event.getString("player") == playerName)
                if (event.has("revision") && event.getLong("revision") != gate.revision) return
                ackIdentity = event.getJSONObject("identity"); ackSequence = 0
                helpScope.bind(ackIdentity!!.getString("session"), ackIdentity!!.getLong("turn"), epoch, gate.revision)
                player.bind(Binding(epoch, checkNotNull(playerName), event.getInt("stream")))
                images?.bind(ImageScope(ackIdentity!!.getString("session"), ackIdentity!!.getLong("turn"), epoch, gate.revision))
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
                    gate.noResponseExpected()
                    if (player.suspended) player.resumeConfirmedNoise()
                    send("resume_noise"); outputBusy = player.hasPending
                }
                "thinking" -> status("listening")
                "new_turn" -> interrupt(event.optString("intent", ""))
                "stop" -> { gate.noResponseExpected(); interrupt() }
                else -> status("clarify") // Unknown recognition never resumes audio.
            }
            }
            "revoke" -> { images?.clear(); player.stop(); ackIdentity = null; hideImage() }
            "image_ready" -> {
                val ready = imageReady(event) ?: return
                if (event.getString("source") != "default" || (!event.isNull("fallback_reason") &&
                    event.getString("fallback_reason") !in setOf("dynamic_unavailable", "unknown_asset", "asset_invalid"))) return
                images?.ready(ready)
            }
            "hide" -> {
                if (!imageScopeCurrent(event) || event.getString("reason") !in setOf("requested", "input_changed")) return
                images?.clear(); hideImage()
            }
            "reveal" -> if (player.binding != null && !player.suspended) {
                if (event.getString("effect").startsWith("image:")) {
                    val ready = imageReady(event) ?: return
                    if (event.getString("effect") != "image:" + ready.token) return
                    val binding = player.binding ?: return
                    if (event.getString("player") != binding.player || event.getInt("stream") != binding.stream) return
                    images?.reveal(ImageReveal(ready, binding.player, binding.stream, event.getString("segment"), event.getLong("end")))
                } else if (images == null) reveal(event.getString("effect"), event.getInt("topic"))
            }
            "thinking_wait" -> status("thinking")
            "reply_end" -> { completed(event.getLong("head"), event.getInt("public_facts")); outputBusy = false; gate.interaction(); status("listening") }
            "management" -> {
                if (event.getLong("revision") != gate.revision || !helpScope.matches(event.getString("session"),
                    event.getLong("turn"), epoch, gate.revision)) return
                interrupt(); management()
            }
            "failure" -> {
                if (event.has("local_help")) {
                    if (event.optString("code") != "safety") return
                    val help = runCatching {
                        val value = event.getJSONObject("local_help")
                        if (value.keys().asSequence().toSet() != setOf("v", "prompt_id", "reason") ||
                            event.getLong("revision") != gate.revision) null
                        else helpScope.accept(event.getString("session"), event.getLong("turn"), epoch, gate.revision,
                            value.getInt("v"), value.getString("prompt_id"), value.getString("reason"))
                    }.getOrNull() ?: return // stale/malformed help must not close or lend authority to a newer turn
                    interrupt(); status("failure"); localHelp(help)
                } else { interrupt(); status("failure"); failed() }
            }
            else -> error("unknown event")
        }
    }
    private fun recordImageAck(ack: PlaybackAck) {
        if (ack.completed && !player.suspended && ack.binding == player.binding && responseRevision == gate.revision)
            images?.acknowledged(ack.binding.player, ack.binding.stream, ack.segment, ack.head)
    }
    private fun imageScopeCurrent(event: JSONObject): Boolean =
        event.getLong("revision") == gate.revision && helpScope.matches(event.getString("session"),
            event.getLong("turn"), epoch, gate.revision)
    private fun imageReady(event: JSONObject): ImageReady? {
        if (!imageScopeCurrent(event)) return null
        val id = event.getString("asset_id"); val sha = event.getString("sha256")
        if (!id.matches(Regex("[a-z0-9-]{1,64}")) || !sha.matches(Regex("[a-f0-9]{64}"))) return null
        if (event.getString("type") == "image_ready" && (event.getInt("width") != 512 || event.getInt("height") != 512)) return null
        return ImageReady(ImageScope(event.getString("session"), event.getLong("turn"), epoch, gate.revision),
            event.getInt("topic"), event.getString("token"), ImageAsset(id, sha, 512, 512))
    }
    fun input(samples: ShortArray, count: Int, speech: Boolean = true, capturedAt: Long = SystemClock.elapsedRealtime()) {
        if (!permitted()) { samples.fill(0); return }
        val age = SystemClock.elapsedRealtime() - capturedAt
        require(age in 0..20000) { "capture age" }
        require(count in 1..3200)
        val bytes = ByteBuffer.allocate(count * 2).order(ByteOrder.LITTLE_ENDIAN)
        repeat(count) { bytes.putShort(samples[it]) }
        send("input", "pcm" to Base64.encodeToString(bytes.array(), Base64.NO_WRAP), "speech" to speech, "age_ms" to age)
        bytes.array().fill(0)
    }
    fun wake(observedAt: Long = SystemClock.elapsedRealtime()) { if (isAwake) return; isAwake = true; gate.wake(observedAt); send("wake"); status("listening") }
    fun frame(samples: ShortArray, speech: Boolean, capturedAt: Long = SystemClock.elapsedRealtime()) {
        if (speech) gate.speech(capturedAt) else gate.quiet()
        input(samples, samples.size, speech, capturedAt)
        samples.fill(0)
    }
    fun quiet() { gate.quiet() }
    fun candidate() {
        if (player.binding != null && !player.suspended) {
            images?.clear(); player.suspendOutput(); send("suspend")
        }
    }
    fun interrupt(intent: String = "") {
        images?.clear()
        val stopped = player.stop() // First: local mute, generation revoke, flush, stop/release.
        ackIdentity = null; playerName = null; outputBusy = false
        hideImage()
        epoch++; sequence = 0; helpScope.clear()
        if (!stopped.stopped || !stopped.released) { fail("release"); return }
        send("stop", "intent" to intent) // Only after local native calls completed.
    }
    private fun fail(code: String) { close(); status(code); failed() }
    fun close() {
        images?.clear()
        active = false; isAwake = false; outputBusy = false; helpScope.clear()
        player.stop(); ackIdentity = null; hideImage()
        handler.removeCallbacks(pump); handler.removeCallbacks(heartbeat)
        val old = socket; socket = null
        old?.cancel()
    }
}
