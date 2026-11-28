package com.littlebuddy.v2

import com.littlebuddy.v2.parent.PinDiagnostic
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
                           private var playbackSettings: com.littlebuddy.v2.parent.ParentPlaybackSettings = com.littlebuddy.v2.parent.ParentPlaybackSettings(),
                           private val localHelp: (LocalHelpReason) -> Unit = {},
                           private val management: (ManagementEntry) -> Unit = {},
                           private val permitted: () -> Boolean = { true },
                           private var images: ImagePort? = null,
                           private val managed: (ManagementState.Phase) -> Unit = {},
                           private val sessionEnded: () -> Unit = {},
                           private val requiredContract: String? = null,
                           private val ready: () -> Unit = {},
                           private val http: OkHttpClient = OkHttpClient.Builder().retryOnConnectionFailure(false)
                               .followRedirects(false).followSslRedirects(false).proxy(java.net.Proxy.NO_PROXY)
                               .connectTimeout(4, TimeUnit.SECONDS).build(),
                           private val closeTransport: () -> Unit = {},
                           private val diagnosticScope:PinDiagnostic.Scope=PinDiagnostic.Scope(),
                           private val actualOutput: (Boolean)->Unit = {}) {
    fun nativeProof() = player.nativeProof()
    private var controlQuarantined=false
    private var deliveringSafety=false // handler-owned: an accepted safety event must still show text if stop fails
    val quarantined get() = player.quarantined || controlQuarantined
    private val childVolume=ChildVolume(playbackSettings.volume)
    private val managementState = ManagementState(SystemClock::elapsedRealtime)
    @Volatile private var childBlocked = false
    private var managementPending = false
    private var socket: WebSocket? = null
    private var epoch = 0L
    private var sequence = 0L
    private var active = false
    private var wirePoint=PinDiagnostic.WirePoint.NONE
    private var wireKind=PinDiagnostic.WireKind.NONE
    private var compatible = requiredContract == null
    private var compatibilityDeadline=0L
    @Volatile var isAwake = false; private set
    @Volatile var idleSerial = 0L; private set
    @Volatile var inputSerial = 0L; private set
    private var outputBusy = false
    private var responseRevision = -1L
    private val phases=if(ClientPhasePort.enabled())ClientPhases(diagnosticScope,SystemClock::elapsedRealtime) else null
    private val gate: InputGate = InputGate(waits, SystemClock::elapsedRealtime,
        { version -> phases?.clear();entryGate.clear(); childVolume.clear(); images?.inputChanged(); send("advance", "revision" to version); candidate();status("listening") },
        { version -> val seq=sequence;if(send("probe", "revision" to version))phase(ClientPhase.PROBE_SENT,version,seq=seq) },
        { version -> val seq=sequence;if(send("seal", "revision" to version))phase(ClientPhase.SEAL_SENT,version,seq=seq); inputSerial++ ; outputBusy = true;status("thinking") },
        { send("wake_solo", "age_ms" to (15000L - (gateDeadline() - SystemClock.elapsedRealtime()))); outputBusy = true;status("thinking") },
        { send("thinking_prompt", "revision" to gateVersion()); status("waiting_thinking") },
        { isAwake = false; idleSerial++; interrupt(); status("wake") })
    private fun gateDeadline(): Long = gate.responseDeadline
    private fun gateVersion(): Long = gate.revision
    private fun inputEyeStatus()=gate.endpointCompletion?.eyeStatus() ?: "listening"
    private val helpScope = LocalHelpScope()
    private val entryGate=ManagementEntryGate(SystemClock::elapsedRealtime)
    private var ackIdentity: JSONObject? = null
    private var ackSequence = 0L
    private var playerName: String? = null
    private val player = Playback({ createTrack() },
        SystemClock::elapsedRealtime) { ack ->
        observed(ack)
        if (ack.completed && responseRevision == gate.revision && ack.binding.epoch == epoch) gate.effectivePlayed()
        if (!allowAck(ack)) return@Playback
        val identity = ackIdentity ?: return@Playback
        val copy = JSONObject(identity.toString()).put("sequence", ackSequence++)
        val sent = send("ack", "identity" to copy, "player" to ack.binding.player,
             "stream" to ack.binding.stream, "segment" to ack.segment, "head" to ack.head)
        if (sent) recordImageAck(ack)
    }.also { it.observeOutput(::outputObserved) }
    private fun phase(kind:ClientPhase,version:Long=gateVersion(),seq:Long=-1,receivedBoot:Long=-1,accepted:Boolean=true) {
        try {if(phases!=null && active && !childBlocked && permitted())
            phases.event(kind,epoch,gate.revision,gate.capturedLastSpeechBootMs,version,seq,receivedBoot,accepted)
        }catch(_:Throwable){}
    }
    private fun createTrack():AndroidTrack {
        val key=phases?.bindingKey
        return AndroidTrack(handler,com.littlebuddy.v2.parent.ParentPlaybackSettings(childVolume.value,playbackSettings.rate,playbackSettings.durationSeconds),
            phase=if(key==null)null else {metric->
                if(active && !childBlocked && permitted() && epoch==key.epoch && gate.revision==key.revision)
                    phases?.track(key,metric,gate.capturedLastSpeechBootMs)
            }) { fail("route") }
    }
    private fun outputObserved(playing:Boolean) {
        val actual=playing && permitted() && !childBlocked
        try{if(actual && active && responseRevision==gate.revision)player.binding?.let {
            phases?.firstHead(it.epoch,gate.revision,it.stream,gate.capturedLastSpeechBootMs)
        }}catch(_:Throwable){}
        actualOutput(actual)
    }
    private val pump = object : Runnable {
        override fun run() {
            if (!active) return
            if (!permitted()) { fail("lifecycle"); return }
            var step=PinDiagnostic.PumpStep.COMPATIBILITY
            try {
                if (!compatible) check(SystemClock.elapsedRealtime()<compatibilityDeadline)
                step=PinDiagnostic.PumpStep.MANAGEMENT_DEADLINE; managementState.checkDeadline()
                if (compatible && !childBlocked) {
                    step=PinDiagnostic.PumpStep.INPUT_RESPONSE_DEADLINE;gate.checkResponseDeadline()
                    step=PinDiagnostic.PumpStep.PLAYER_TICK;player.tick()
                    step=PinDiagnostic.PumpStep.ENDPOINT_TICK;gate.tick(outputBusy)
                }
            } catch (_: Exception) { fail("playback",step); return }
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
        PinDiagnostic.event(PinDiagnostic.Stage.WSS,PinDiagnostic.Reason.BEGIN)
        active = true
        epoch = 0; sequence = 0; helpScope.clear()
        val request = Request.Builder().url(address).header("Authorization", "Bearer $token").build()
        socket = http.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) { handler.post {
                if (socket !== webSocket || !active) return@post
                PinDiagnostic.event(PinDiagnostic.Stage.WSS,PinDiagnostic.Reason.SUCCESS)
                if (requiredContract!=null) {
                    compatible=false; compatibilityDeadline=SystemClock.elapsedRealtime()+4000
                    send("scope"); status("compatibility")
                } else { compatible=true; status("wake"); ready() }
                pump.run(); heartbeat.run()
            } }
            override fun onMessage(webSocket: WebSocket, text: String) {
                val receivedBoot=if(phases!=null)SystemClock.elapsedRealtime() else -1L
                handler.post {
                if (socket !== webSocket || !active) return@post
                try { receive(text,receivedBoot) } catch (error: Exception) { PinDiagnostic.runtimeError(PinDiagnostic.Stage.PROTOCOL,error); fail("protocol") }
            } }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                handler.post { if (socket === webSocket && active) {
                    PinDiagnostic.runtimeError(PinDiagnostic.Stage.WSS,t)
                    if(response?.code==401 || response?.code==403)
                        PinDiagnostic.event(PinDiagnostic.Stage.WSS,PinDiagnostic.Reason.AUTH_DENIED)
                    else if(response!=null && response.code>=400)
                        PinDiagnostic.event(PinDiagnostic.Stage.WSS,PinDiagnostic.Reason.HTTP_FAILED)
                    fail("network")
                } }
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
    private fun receive(text: String,receivedBoot:Long=-1) {
        if (!permitted()) { close(); return }
        wirePoint=PinDiagnostic.WirePoint.ENVELOPE;wireKind=PinDiagnostic.WireKind.UNPARSED
        require(text.length <= 16000 && text.toByteArray(Charsets.UTF_8).size <= 16000)
        wirePoint=PinDiagnostic.WirePoint.JSON_PARSE
        val event = JSONObject(text)
        wirePoint=PinDiagnostic.WirePoint.ENVELOPE
        require(event.getInt("v") == 2)
        if (event.getLong("epoch") != epoch) return
        val kind=event.getString("type");wireKind=PinDiagnostic.wireKind(kind);wirePoint=PinDiagnostic.WirePoint.DISPATCH
        if (childBlocked && kind !in setOf("scope", "management_state", "revoke", "failure")) return
        if (!compatible && kind!="scope") { if (kind=="failure") fail("incompatible"); return }
        when (kind) {
            "scope" -> {
                wirePoint=PinDiagnostic.WirePoint.SCOPE_BIND
                if (!compatible) {
                    if (event.getLong("epoch")!=epoch || event.getLong("revision")!=gate.revision ||
                        !ReleaseCompatibility.accepts(event.getInt("v"),event.optString("protocol_contract", ""),
                            event.optInt("management_v",-1),event.optString("session",""),event.optLong("turn",-1),
                            event.getLong("epoch"),event.optLong("revision",-1),event.optString("state","")) ||
                        event.optString("protocol_contract","")!=requiredContract) { fail("incompatible"); return }
                    bindNormalScope(managementScope(event)); compatible=true; PinDiagnostic.event(PinDiagnostic.Stage.PROTOCOL,PinDiagnostic.Reason.READY); status("wake"); ready(); return
                }
                if (!managementPending) {
                    if (event.getLong("revision")==gate.revision && ReleaseCompatibility.accepts(event.getInt("v"),
                        event.optString("protocol_contract",""),event.optInt("management_v",-1),event.optString("session",""),
                        event.optLong("turn",-1),epoch,event.optLong("revision",-1),event.optString("state","")))
                        bindNormalScope(managementScope(event))
                    return
                }
                if (event.getInt("management_v") != 1 ||
                    event.getString("state") !in setOf("active", "waiting_wake")) return
                val request = managementState.scoped(managementScope(event)) ?: return
                moveManagementEpoch(request.scope)
                send("management_pause", "session" to request.scope.session, "turn" to request.scope.turn,
                    "revision" to request.scope.revision)
            }
            "management_state" -> {
                if (event.getInt("management_v") != 1) return
                val scope=managementScope(event)
                when (event.getString("state")) {
                    "expired" -> fail("expired")
                    "paused" -> if (managementState.paused(scope,event.getString("pause"))) {
                        managementPending=false; managed(ManagementState.Phase.PAUSED)
                    }
                    "waiting_wake" -> if (event.has("pause") && event.isNull("pause") && managementState.waiting(scope)) {
                        managementPending=false; isAwake=false; idleSerial++
                        managed(ManagementState.Phase.WAITING_WAKE)
                    }
                }
            }
            "endpoint" -> {
                val completion=Completion.valueOf(event.getString("completion").uppercase())
                val version=event.getLong("revision")
                var accepted=false
                try{accepted=gate.decision(version,completion)}finally{
                    phase(ClientPhase.ENDPOINT_RECEIVED,version,receivedBoot=receivedBoot,accepted=accepted)
                }
                if(accepted)status(completion.eyeStatus())
            }
            "open" -> {
                if (event.getLong("revision") != gate.revision) {phase(ClientPhase.OPEN_RECEIVED,event.getLong("revision"),receivedBoot=receivedBoot,accepted=false);return}
                if (event.has("session") && event.has("turn")) {
                    bindNormalScope(managementScope(event))
                }
                outputBusy = true
                responseRevision = gate.revision
                check(player.binding == null)
                phase(ClientPhase.OPEN_RECEIVED,receivedBoot=receivedBoot)
                playerName = UUID.randomUUID().toString()
                val seq=sequence
                val sent=if (images != null) send("bind", "player" to checkNotNull(playerName), "features" to org.json.JSONArray().put("images_v2"), "image_contract" to ReleaseCompatibility.CONTRACT)
                else send("bind", "player" to checkNotNull(playerName))
                if(sent)phase(ClientPhase.BIND_SENT,seq=seq)
            }
            "bound" -> {
                wirePoint=PinDiagnostic.WirePoint.PLAYER_BIND
                require(event.getString("player") == playerName)
                if (event.has("revision") && event.getLong("revision") != gate.revision) return
                ackIdentity = event.getJSONObject("identity"); ackSequence = 0
                bindNormalScope(ManagementScope(ackIdentity!!.getString("session"),ackIdentity!!.getLong("turn"),epoch,gate.revision))
                try{if(active && !childBlocked && permitted() && responseRevision==gate.revision && player.binding==null)
                    phases?.bound(epoch,gate.revision,event.getInt("stream"),gate.capturedLastSpeechBootMs,receivedBoot)
                }catch(_:Throwable){}
                player.bind(Binding(epoch, checkNotNull(playerName), event.getInt("stream")))
                images?.bind(ImageScope(ackIdentity!!.getString("session"), ackIdentity!!.getLong("turn"), epoch, gate.revision))
            }
            "audio" -> {
                wirePoint=PinDiagnostic.WirePoint.AUDIO_VALIDATE
                val data = Base64.decode(event.getString("pcm"), Base64.NO_WRAP)
                require(data.isNotEmpty() && data.size <= 4800 && data.size % 2 == 0)
                val pcm = ShortArray(data.size/2)
                ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(pcm)
                val binding = Binding(epoch, event.getString("player"), event.getInt("stream"))
                wirePoint=PinDiagnostic.WirePoint.AUDIO_ENQUEUE
                val enqueued=player.enqueue(AudioPacket(binding, event.getString("segment"), event.getLong("start"),
                                           event.getLong("end"), pcm))
                try{if(enqueued && binding==player.binding && responseRevision==gate.revision && active && !childBlocked && permitted())
                    phases?.firstAudio(epoch,gate.revision,binding.stream,gate.capturedLastSpeechBootMs,receivedBoot)
                }catch(_:Throwable){}
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
                "thinking" -> status("waiting_thinking")
                "unknown" -> {
                    // A delayed classification cannot revoke a response that has already bound.
                    if(player.binding!=null && !player.suspended && responseRevision==gate.revision)return
                    val resolvedEpoch=epoch
                    val resolvedRevision=event.getLong("revision")
                    if(gate.unrecognized(resolvedRevision)) {
                        interrupt() // Original mute/stop/release, epoch/sequence migration and server stop.
                        if(active && !childBlocked && permitted() && !quarantined && epoch==resolvedEpoch+1 && gate.revision==resolvedRevision) {
                            inputSerial++ // Completed input, not a new response grant; Capture resets its per-expression counter.
                            try{phases?.event(ClientPhase.INPUT_UNRECOGNIZED,resolvedEpoch,resolvedRevision,
                                gate.capturedLastSpeechBootMs,wireRevision=resolvedRevision)}catch(_:Throwable){}
                            status("clarify")
                        }
                    }
                }
                "new_turn" -> interrupt(event.optString("intent", ""),preservePublicImage=true)
                "stop" -> { gate.noResponseExpected(); interrupt() }
                else -> status("clarify") // Unknown recognition never resumes audio.
            }
            }
            "revoke" -> { phases?.clear();images?.outputRevoked(); player.stop(); ackIdentity = null; hideImage() }
            "volume" -> {
                if(!imageScopeCurrent(event) || wireInt(event,"control_v")!=1 || !managementState.mediaAllowed ||
                    SystemClock.elapsedRealtime()>=gate.responseDeadline) return
                val level=childVolume.accept(managementScope(event),event.getString("token"),event.getString("direction")) ?: return
                player.setVolume(level);gate.noResponseExpected()
            }
            "image_status" -> {
                if(imageScopeCurrent(event) && wireInt(event,"image_v")==2 && event.getString("state")=="unavailable" &&
                    event.getString("reason")=="image_unavailable") { images?.clear();hideImage() }
            }
            "image_begin" -> {
                val ready=imageReady(event) ?: return
                require(ready.source=="dynamic" && event.getString("encoding")=="base64")
                images?.begin(ready,wireInt(event,"bytes"),wireInt(event,"chunks"),wireInt(event,"chunk_bytes"),event.getLong("retain_ms"))
            }
            "image_chunk" -> {
                val ready=imageReady(event) ?: return
                require(ready.source=="dynamic")
                val encoded=event.getString("data")
                require(encoded.length in 4..10924 && encoded.matches(Regex("[A-Za-z0-9+/]*={0,2}")))
                val data=Base64.decode(encoded,Base64.NO_WRAP)
                require(data.size in 1..8192 && Base64.encodeToString(data,Base64.NO_WRAP)==encoded)
                try { images?.chunk(ready,wireInt(event,"index"),wireInt(event,"offset"),data) } finally { data.fill(0) }
            }
            "image_ready" -> {
                val ready=imageReady(event) ?: return
                if(ready.source=="default" && (!event.isNull("fallback_reason") &&
                    event.getString("fallback_reason") !in setOf("dynamic_unavailable","unknown_asset","asset_invalid"))) return
                images?.readyV2(ready,event.getLong("retain_ms"))
            }
            "image_display" -> {
                val ready=imageReady(event) ?: return
                if(event.getString("action")=="hide" && event.optString("reason")=="expired" &&
                    event.optBoolean("eyes",false) && event.getLong("duration_ms")==0L) {
                    images?.expired(ready,event.getLong("retain_ms"));return
                }
                val binding=player.binding ?: return
                if(player.suspended || event.getString("player")!=binding.player || event.getInt("stream")!=binding.stream)return
                images?.display(ImageReveal(ready,binding.player,binding.stream,event.getString("segment"),event.getLong("end")),
                    event.getString("action"),event.getLong("duration_ms"),event.getLong("retain_ms"))
            }
            "hide" -> {
                if(!imageScopeCurrent(event) || event.getString("reason") !in setOf("requested","input_changed"))return
                images?.inputChanged()
                hideImage()
            }
            "reveal" -> if(images==null && player.binding!=null && !player.suspended) {
                reveal(event.getString("effect"),event.getInt("topic"))
            }
            "thinking_wait" -> status(inputEyeStatus())
            "reply_end" -> { completed(event.getLong("head"), event.getInt("public_facts")); outputBusy = false; gate.interaction(); status(inputEyeStatus()) }
            "session_end" -> {
                if (!SessionTermination.accepts(event.optString("reason"), active, permitted(), childBlocked,
                    event.optLong("epoch",-1)==epoch && imageScopeCurrent(event))) return
                PinDiagnostic.runtime(PinDiagnostic.RuntimeEvent(PinDiagnostic.RuntimeStage.SESSION_END,diagnosticScope,
                    source=if(event.optString("reason")=="session_expired")PinDiagnostic.FailSource.EXPIRED else PinDiagnostic.FailSource.NONE,
                    wire=PinDiagnostic.WireKind.SESSION_END,point=PinDiagnostic.WirePoint.DISPATCH))
                close(); sessionEnded()
            }
            "management" -> {
                if (event.getLong("revision") != gate.revision || !helpScope.matches(event.getString("session"),
                    event.getLong("turn"), epoch, gate.revision)) return
                val entry=entryGate.issue(managementScope(event),gate.responseDeadline) ?: return
                management(entry)
            }
            "failure" -> {
                if (childBlocked) { fail("management"); return }
                if (event.has("local_help")) {
                    if (event.optString("code") != "safety") return
                    val help = runCatching {
                        val value = event.getJSONObject("local_help")
                        if (value.keys().asSequence().toSet() != setOf("v", "prompt_id", "reason") ||
                            event.getLong("revision") != gate.revision) null
                        else helpScope.accept(event.getString("session"), event.getLong("turn"), epoch, gate.revision,
                            value.getInt("v"), value.getString("prompt_id"), value.getString("reason"))
                    }.getOrNull() ?: return // stale/malformed help must not close or lend authority to a newer turn
                    PinDiagnostic.runtime(PinDiagnostic.RuntimeEvent(PinDiagnostic.RuntimeStage.CLIENT_FAIL,diagnosticScope,
                        source=PinDiagnostic.FailSource.SERVER_SAFETY,wire=wireKind,point=wirePoint))
                    deliveringSafety=true
                    try { interrupt(); status("failure"); localHelp(help) }
                    finally { deliveringSafety=false }
                } else { fail(ServerFailure.classify(event.optString("code")).localCode) }
            }
            else -> {wirePoint=PinDiagnostic.WirePoint.UNKNOWN_EVENT;error("unknown event")}
        }
    }
    private fun bindNormalScope(scope: ManagementScope) {
        helpScope.bind(scope.session,scope.turn,scope.epoch,scope.revision)
        managementState.normal(scope)
        childVolume.bind(scope)
        entryGate.bind(scope) // Both normal consumers are ready before any entry/ready callback.
    }
    fun acceptManagementEntry(entry: ManagementEntry, decision: ()->Boolean): Boolean =
        active && permitted() && !childBlocked && entryGate.accept(entry,epoch,gate.revision,decision)
    private fun managementScope(event: JSONObject) = ManagementScope(event.getString("session"), event.getLong("turn"),
        event.getLong("epoch"),event.getLong("revision"))
    private fun moveManagementEpoch(scope: ManagementScope) {
        phases?.clear()
        epoch=scope.epoch; sequence=0; gate.managementWaiting(scope.revision)
        ackIdentity=null; playerName=null; helpScope.clear(); entryGate.clear(); childVolume.clear(); images?.clear()
    }
    /** Caller has already stopped the children's recorder; no network action until native release confirms. */
    fun stopForManagement(): Boolean {
        phases?.clear()
        childBlocked=true; isAwake=false; idleSerial++; images?.clear(); hideImage()
        val stopped=player.stop(); ackIdentity=null; playerName=null; outputBusy=false
        if (!stopped.stopped || !stopped.released) { fail("release"); return false }
        return true
    }
    fun pauseManagement(): Boolean {
        if (!active || !childBlocked) return false
        return try { managementState.begin(epoch,gate.revision); managementPending=true; send("scope") }
            catch (_: Exception) { fail("management"); false }
    }
    fun resumeManagement(settings: com.littlebuddy.v2.parent.ParentPlaybackSettings, route: ImagePort?): Boolean {
        if (!active) return false
        return try {
            val request=managementState.resume() ?: return false
            images?.clear(); images=route; playbackSettings=settings; childVolume.tighten(settings.volume); managementPending=true; moveManagementEpoch(request.scope)
            send("management_resume", "session" to request.scope.session, "turn" to request.scope.turn,
                "revision" to request.scope.revision, "pause" to checkNotNull(request.receipt))
        } catch (_: Exception) { fail("management"); false }
    }
    private fun recordImageAck(ack: PlaybackAck) {
        if (ack.completed && !player.suspended && ack.binding == player.binding && responseRevision == gate.revision)
            images?.acknowledged(ack.binding.player, ack.binding.stream, ack.segment, ack.head)
    }
    private fun imageScopeCurrent(event: JSONObject): Boolean =
        event.getLong("revision") == gate.revision && helpScope.matches(event.getString("session"),
            event.getLong("turn"), epoch, gate.revision)
    private fun wireInt(event: JSONObject, name: String): Int {
        val number=event.get(name);require(number is Int || number is Long)
        val value=(number as Number).toLong();require(value in 0..Int.MAX_VALUE.toLong());return value.toInt()
    }
    private fun imageReady(event: JSONObject): ImageReady? {
        if(!imageScopeCurrent(event) || wireInt(event,"image_v")!=2)return null
        val id=event.getString("asset_id");val sha=event.getString("sha256");val source=event.getString("source")
        val width=wireInt(event,"width");val height=wireInt(event,"height")
        if(!id.matches(Regex("[a-z0-9-]{1,64}")) || !sha.matches(Regex("[a-f0-9]{64}")) ||
            source !in setOf("default","dynamic") || width !in 512..2048 || height !in 512..2048 ||
            (source=="default" && (width!=512 || height!=512)))return null
        return ImageReady(ImageScope(event.getString("session"),event.getLong("turn"),epoch,gate.revision),
            wireInt(event,"topic"),event.getString("token"),ImageAsset(id,sha,width,height),event.getString("image_id"),source)
    }
    fun input(samples: ShortArray, count: Int, speech: Boolean = true, capturedAt: Long = SystemClock.elapsedRealtime()) {
        if (!permitted() || !compatible || childBlocked || !managementState.mediaAllowed) { samples.fill(0); return }
        val age = SystemClock.elapsedRealtime() - capturedAt
        require(age in 0..20000) { "capture age" }
        require(count in 1..3200)
        val bytes = ByteBuffer.allocate(count * 2).order(ByteOrder.LITTLE_ENDIAN)
        repeat(count) { bytes.putShort(samples[it]) }
        send("input", "pcm" to Base64.encodeToString(bytes.array(), Base64.NO_WRAP), "speech" to speech, "age_ms" to age)
        bytes.array().fill(0)
    }
    fun wake(observedAt: Long = SystemClock.elapsedRealtime(),wakeTailFrame:Long=-1,captureFrame:Long=-1,wakeRelativeMs:Long=-1) {
        if (isAwake || !active || !compatible || !permitted() || !managementState.wake()) return
        childBlocked=false; isAwake = true; gate.wake(observedAt)
        PinDiagnostic.runtime(PinDiagnostic.RuntimeEvent(PinDiagnostic.RuntimeStage.WAKE_ACCEPTED,diagnosticScope,
            wakeFrame=wakeTailFrame,readFrame=captureFrame,wakeRelativeMs=wakeRelativeMs,
            wakeLagMs=SystemClock.elapsedRealtime()-observedAt))
        send("wake"); status("listening")
    }
    fun frame(samples: ShortArray, speech: Boolean, capturedAt: Long = SystemClock.elapsedRealtime()) {
        if (childBlocked || !managementState.mediaAllowed) { samples.fill(0); return }
        if (speech) gate.speech(capturedAt) else gate.quiet()
        input(samples, samples.size, speech, capturedAt)
        samples.fill(0)
    }
    fun quiet() { if (!childBlocked) gate.quiet() }
    fun candidate() {
        if (childBlocked) return
        if (player.binding != null && !player.suspended) {
            images?.inputChanged(); player.suspendOutput(); send("suspend")
        }
    }
    fun interrupt(intent: String = "", preservePublicImage: Boolean = false) {
        if(preservePublicImage)images?.inputChanged() else images?.clear()
        phases?.clear()
        val stopped = player.stop() // First: local mute, generation revoke, flush, stop/release.
        ackIdentity = null; playerName = null; outputBusy = false
        hideImage()
        epoch++; sequence = 0; helpScope.clear(); entryGate.clear(); childVolume.clear()
        if (!stopped.stopped || !stopped.released) { fail("release"); return }
        send("stop", "intent" to intent) // Only after local native calls completed.
    }
    private fun fail(code: String,pumpStep:PinDiagnostic.PumpStep=PinDiagnostic.PumpStep.NONE) {
        PinDiagnostic.runtime(PinDiagnostic.RuntimeEvent(PinDiagnostic.RuntimeStage.CLIENT_FAIL,diagnosticScope,
            source=PinDiagnostic.failSource(code),wire=if(code=="protocol" || code.startsWith("server_"))wireKind else PinDiagnostic.WireKind.NONE,
            point=if(code=="protocol" || code.startsWith("server_"))wirePoint else PinDiagnostic.WirePoint.NONE,pump=pumpStep))
        PinDiagnostic.event(PinDiagnostic.Stage.PROTOCOL,when(code) {
            "incompatible"->PinDiagnostic.Reason.INCOMPATIBLE
            "closed"->PinDiagnostic.Reason.CLOSED
            "network"->PinDiagnostic.Reason.NETWORK
            "release"->PinDiagnostic.Reason.RELEASE_FAILED
            else->PinDiagnostic.Reason.PROTOCOL_FAILED
        })
        val pending=childBlocked
        if (pending && code!="expired") controlQuarantined=true
        close(); if (pending) managed(ManagementState.Phase.DEAD); status(code)
        if (!deliveringSafety) failed()
    }
    fun close() {
        PinDiagnostic.runtime(PinDiagnostic.RuntimeEvent(PinDiagnostic.RuntimeStage.CLIENT_CLOSE_BEGIN,diagnosticScope))
        phases?.clear()
        managementState.close(); entryGate.clear(); childVolume.clear(); childBlocked=true; managementPending=false
        images?.clear()
        active = false; isAwake = false; outputBusy = false; helpScope.clear()
        player.stop(); ackIdentity = null; hideImage()
        handler.removeCallbacks(pump); handler.removeCallbacks(heartbeat)
        val old = socket; socket = null
        old?.cancel()
        closeTransport(); http.connectionPool.evictAll(); http.dispatcher.cancelAll()
        PinDiagnostic.runtime(PinDiagnostic.RuntimeEvent(PinDiagnostic.RuntimeStage.CLIENT_CLOSE_END,diagnosticScope))
    }
}
