package com.littlebuddy.v2.parent

import java.util.concurrent.atomic.AtomicInteger

/** Closed vocabulary only. No authentication data or exception text can enter this port.
 * Disabled by default. The diagnostic adapter must be nonblocking; all failures are isolated. */
internal object PinDiagnostic {
    enum class Stage { PROMPT, TAKE, APPROVE, RECEIPT, PAGE, TICK, SAVE, CONSUME, DERIVE, COMMIT, RESULT, RENDER, CONFIG, SOCKET_CREATE, SOCKET_OPTIONS, SOCKET_MAP, SOCKET_CONNECT, TLS, ERROR_CHAIN, ERROR_SITE, SSH, FORWARD, SOCKET, WSS, PROTOCOL, CAPTURE_NATIVE, CAPTURE_MODEL, CAPTURE_STARTUP, CAPTURE_READ, CAPTURE_CLOCK, CAPTURE_QUEUE, CAPTURE_KWS, CAPTURE_CLEANUP, HELP, TECHNICAL }
    enum class Reason { BEGIN, SUCCESS, REJECTED, ERROR, MISSING, EXPIRED, NO_FOCUS, CANCEL,
        INVALIDATED, TICK_OWNER_INVALID, SAVE_IN_PROGRESS, EARLY_REJECT, CHALLENGE_REJECT,
        PIN_MISMATCH, STALE_CALLBACK, UNOWNED, LOCKED, AUTHORIZED, COOLDOWN, QUARANTINED,
        SECURITY_ERROR, IO_ERROR, STATE_ERROR, OTHER_ERROR, TLS_HANDSHAKE, TLS_PEER, SSH_ERROR, TIMEOUT, ARGUMENT_ERROR, CONFIG_LOAD_FAILED, CONFIG_MIGRATION_FAILED, CONFIG_CHILD_MISSING, CONFIG_CONNECTION_MISSING, READY, SAVED_LOCAL, NO_CONFIG, HOLD, PARENT_RETRY, RETURN, NETWORK, CLOSED, PROTOCOL_FAILED, INCOMPATIBLE, CAPTURE_FAILED, RELEASE_FAILED, TLS_ERROR, AUTH_DENIED, HTTP_FAILED, CONNECT_FAILED, DNS_FAILED, SOCKET_ERROR, EOF_ERROR, INTERRUPTED_IO, SITE_MAP, SITE_CONNECT, SITE_OKHTTP_CONNECT, SITE_TLS, SITE_UNKNOWN, SITE_JAVA_SOCKET, SITE_CONSCRYPT, TARGET_UNRESOLVED, TARGET_HOST, TARGET_PORT, FORWARD_UNAVAILABLE }
    data class Scope(val activity:Long=0,val transport:Long=0,val capture:Long=0)
    enum class RuntimeStage { ACTIVITY_CREATE, ACTIVITY_RESUME, ACTIVITY_PAUSE, ACTIVITY_FOCUS_GAIN, ACTIVITY_FOCUS_LOSS, ACTIVITY_NEW_INTENT,
        EXPIRY_CAPTURE_RETRY, RECOVERY_LOCAL, RECOVERY_CONNECT, RECOVERY_BIND, RECOVERY_IMPORTED, RECOVERY_HOLD, SERVICE_CUE_BEGIN, SERVICE_CUE_HEAD, SERVICE_CUE_END, SERVICE_CUE_CANCEL,
        CAPTURE_OPERATION, WAKE_ACCEPTED, SESSION_END, CLIENT_FAIL, CLIENT_CLOSE_BEGIN, CLIENT_CLOSE_END, TRANSPORT_RETIRE, CAPTURE_START, CAPTURE_CANCEL,
        CAPTURE_STOP_BEGIN, CAPTURE_STOP_END, CAPTURE_FAILURE, CAPTURE_RELEASE, WORKER_JOINED, FAILURE_UI_APPLY, FAILURE_UI_RETIRED }
    enum class PumpStep { NONE, COMPATIBILITY, MANAGEMENT_DEADLINE, INPUT_RESPONSE_DEADLINE, PLAYER_TICK, ENDPOINT_TICK }
    enum class CaptureOperation { NONE, NATIVE_READ, TIMESTAMP, KWS, KWS_REARM, MODEL_INIT, CLEANUP, NATIVE_START }
    enum class FailSource { NONE, RECEIVE_PROTOCOL, PLAYBACK_PUMP, ROUTE, BACKPRESSURE, LIFECYCLE, MANAGEMENT, EXPIRED, INCOMPATIBLE, NETWORK, CLOSED, RELEASE, SERVER_TIMEOUT, SERVER_QUOTA, SERVER_VOICE, SERVER_SAFETY, SERVER_AUTH, SERVER_UNAVAILABLE, SERVER_UNKNOWN, OTHER }
    enum class WireKind { NONE, UNPARSED, SCOPE, OPEN, BOUND, AUDIO, DECISION, REVOKE, IMAGE, MANAGEMENT, FAILURE, SESSION_END, OTHER }
    enum class WirePoint { NONE, ENVELOPE, JSON_PARSE, DISPATCH, SCOPE_BIND, PLAYER_BIND, AUDIO_VALIDATE, AUDIO_ENQUEUE, UNKNOWN_EVENT }
    data class RuntimeEvent(val stage:RuntimeStage,val scope:Scope,val source:FailSource=FailSource.NONE,
        val wire:WireKind=WireKind.NONE,val point:WirePoint=WirePoint.NONE,val cancelled:Boolean=false,
        val allowed:Boolean=false,val stopRequested:Boolean=false,val nativeReleased:Boolean=false,val workerJoined:Boolean=false,
        val operation:CaptureOperation=CaptureOperation.NONE,val currentTransport:Long=-1,val currentCapture:Long=-1,val restored:Boolean=false,val launcher:Boolean=false,val pump:PumpStep=PumpStep.NONE,
        val episode:Long=-1,val generation:Long=-1,val wakeBootMs:Long=-1,
        val operationNs:Long=-1,val wakeFrame:Long=-1,val readFrame:Long=-1,val wakeRelativeMs:Long=-1,val wakeLagMs:Long=-1)
    private val activitySequence=java.util.concurrent.atomic.AtomicLong()
    fun nextActivity()=activitySequence.incrementAndGet()
    @Volatile private var runtimeSink:((RuntimeEvent)->Unit)?=null
    fun installRuntime(value:((RuntimeEvent)->Unit)?) {runtimeSink=value}
    fun runtime(value:RuntimeEvent) {try{runtimeSink?.invoke(value)}catch(_:Throwable){}}
    fun failSource(code:String)=when(code) {
        "server_timeout"->FailSource.SERVER_TIMEOUT; "server_quota"->FailSource.SERVER_QUOTA
        "server_voice"->FailSource.SERVER_VOICE; "server_safety"->FailSource.SERVER_SAFETY
        "server_auth"->FailSource.SERVER_AUTH; "server_unavailable"->FailSource.SERVER_UNAVAILABLE
        "server_unknown"->FailSource.SERVER_UNKNOWN
        "protocol"->FailSource.RECEIVE_PROTOCOL; "playback"->FailSource.PLAYBACK_PUMP
        "route"->FailSource.ROUTE; "backpressure"->FailSource.BACKPRESSURE; "lifecycle"->FailSource.LIFECYCLE
        "management"->FailSource.MANAGEMENT; "expired"->FailSource.EXPIRED; "incompatible"->FailSource.INCOMPATIBLE
        "network"->FailSource.NETWORK; "closed"->FailSource.CLOSED; "release"->FailSource.RELEASE
        else->FailSource.OTHER
    }
    fun wireKind(code:String)=when(code) {
        "scope"->WireKind.SCOPE;"open"->WireKind.OPEN;"bound"->WireKind.BOUND;"audio"->WireKind.AUDIO
        "decision","gate"->WireKind.DECISION;"revoke"->WireKind.REVOKE
        "image_begin","image_chunk","image_ready","image_display","image_hide","image_unavailable","reveal"->WireKind.IMAGE
        "management","management_state"->WireKind.MANAGEMENT;"failure"->WireKind.FAILURE;"session_end"->WireKind.SESSION_END
        else->WireKind.OTHER
    }
    private val sequence = AtomicInteger()
    @Volatile private var sink: ((Int, Long, Stage, Reason) -> Unit)? = null
    fun install(adapter: ((Int, Long, Stage, Reason) -> Unit)?) { sink = adapter }
    fun begin() { if (sink != null) { sequence.incrementAndGet(); event(Stage.PROMPT, Reason.BEGIN) } }
    fun beginRuntime() { if (sink != null) { sequence.incrementAndGet(); event(Stage.CONFIG, Reason.BEGIN) } }
    /** Closed exception categories and source-site enums only: never emit messages, dynamic class names, frames or response bodies. */
    fun runtimeError(stage: Stage, error: Throwable) {
        try {
        var item: Throwable? = error
        var reason = Reason.OTHER_ERROR
        repeat(4) {
            val e = item ?: return@repeat
            val category = when {
                e is javax.net.ssl.SSLPeerUnverifiedException -> Reason.TLS_PEER
                e is javax.net.ssl.SSLHandshakeException -> Reason.TLS_HANDSHAKE
                e is javax.net.ssl.SSLException -> Reason.TLS_ERROR
                e.javaClass.name == "com.jcraft.jsch.JSchException" -> Reason.SSH_ERROR
                e is java.net.SocketTimeoutException -> Reason.TIMEOUT
                e is java.net.ConnectException -> Reason.CONNECT_FAILED
                e is java.net.UnknownHostException -> Reason.DNS_FAILED
                e is java.net.ProtocolException -> Reason.PROTOCOL_FAILED
                e is java.security.GeneralSecurityException || e is SecurityException -> Reason.SECURITY_ERROR
                e is IllegalStateException -> Reason.STATE_ERROR
                e is IllegalArgumentException -> Reason.ARGUMENT_ERROR
                e is java.net.SocketException -> Reason.SOCKET_ERROR
                e is java.io.EOFException -> Reason.EOF_ERROR
                e is java.io.InterruptedIOException -> Reason.INTERRUPTED_IO
                e is java.io.IOException -> Reason.IO_ERROR
                else -> Reason.OTHER_ERROR
            }
            if (reason == Reason.OTHER_ERROR || reason == Reason.IO_ERROR) reason = category
            event(Stage.ERROR_CHAIN, category)
            val site = e.stackTrace.firstOrNull { it.className.startsWith("com.littlebuddy.v2.") || it.className == "okhttp3.internal.connection.RealConnection" || it.className == "java.net.Socket" || it.className.startsWith("com.android.org.conscrypt.") }
            event(Stage.ERROR_SITE, when {
                site?.className == "com.littlebuddy.v2.transport.V2Forwarding" -> Reason.SITE_MAP
                site?.className == "com.littlebuddy.v2.transport.V2MappedSocket" -> Reason.SITE_CONNECT
                site?.className == "okhttp3.internal.connection.RealConnection" && site.methodName == "connectTls" -> Reason.SITE_TLS
                site?.className == "okhttp3.internal.connection.RealConnection" -> Reason.SITE_OKHTTP_CONNECT
                site?.className == "java.net.Socket" -> Reason.SITE_JAVA_SOCKET
                site?.className?.startsWith("com.android.org.conscrypt.") == true -> Reason.SITE_CONSCRYPT
                else -> Reason.SITE_UNKNOWN
            })
            item = e.cause?.takeIf { it !== e }
        }
        event(stage, reason)
        } catch (_: Throwable) { event(stage, Reason.OTHER_ERROR) }
    }

    fun event(stage: Stage, reason: Reason) {
        try { sink?.invoke(sequence.get(), System.nanoTime() / 1_000_000, stage, reason) }
        catch (_: Throwable) { /* Observability must never affect authorization. */ }
    }
    fun observe(stage: Stage, reason: () -> Reason) {
        try { if (sink != null) event(stage, reason()) } catch (_: Throwable) { }
    }
    fun error(stage: Stage, error: Exception) = event(stage, when (error) {
        is java.security.GeneralSecurityException -> Reason.SECURITY_ERROR
        is java.io.IOException -> Reason.IO_ERROR
        is IllegalStateException -> Reason.STATE_ERROR
        else -> Reason.OTHER_ERROR
    })
}

/** Closed scalar vocabulary; never accepts a binding, key, endpoint, token or exception text. */
internal object ConfigurationDiagnostic {
    enum class Stage { WORKER, STORE_PRESENCE, LEGACY_ALIAS, LEGACY_CERT, MARKER_READ, BINDING, MARKER_WRITE,
        ISOLATED_MARKER, ISOLATED_PRESENCE, ISOLATED_OPEN, ISOLATED_COMMIT_MARKER, DOMAIN_OPEN, STORE_READ, STORE_COMMIT, KEY_PRESENCE, KEY_LOAD, KEY_CREATE, PRESET, MIGRATION, CHILD_READ, COMPLETE }
    enum class Reason { BEGIN, SUCCESS, PRESENT, ABSENT, BUSY, QUARANTINED, UNCHANGED,
        REJECTED, EMPTY, NO_CONNECTION, LEGACY_UNREADABLE_ISOLATED, SECURITY, BAD_TAG, INVALID_KEY, IO, STATE, ARGUMENT, OTHER }
    data class Event(val attempt:Long,val stage:Stage,val reason:Reason)
    private val sequence=java.util.concurrent.atomic.AtomicLong()
    private val current=ThreadLocal<Long>()
    @Volatile private var sink:((Event)->Unit)?=null
    fun install(value:((Event)->Unit)?) { sink=value }
    fun event(stage:Stage,reason:Reason) { try { sink?.invoke(Event(current.get()?:0,stage,reason)) } catch(_:Throwable){} }
    fun <T> attempt(block:()->T):T {
        val previous=current.get();current.set(sequence.incrementAndGet())
        try{return block()}finally{if(previous==null)current.remove() else current.set(previous)}
    }
    fun category(error:Exception)=when(error) {
        is javax.crypto.AEADBadTagException -> Reason.BAD_TAG
        is java.security.InvalidKeyException, is java.security.UnrecoverableKeyException -> Reason.INVALID_KEY
        is java.security.GeneralSecurityException, is SecurityException -> Reason.SECURITY
        is java.io.IOException -> Reason.IO
        is IllegalStateException -> Reason.STATE
        is IllegalArgumentException -> Reason.ARGUMENT
        else -> Reason.OTHER
    }
    /** Persistence must retain the exact exception type (especially revoked final commits). */
    fun <T> observe(stage:Stage,block:()->T):T {
        event(stage,Reason.BEGIN)
        try{return block().also{event(stage,Reason.SUCCESS)}}
        catch(error:Exception){event(stage,category(error));throw error}
    }
    fun <T> step(stage:Stage,block:()->T):T {
        event(stage,Reason.BEGIN)
        try {return block().also{event(stage,Reason.SUCCESS)}}
        catch(error:ConfigurationFailure){throw error}
        catch(error:Exception){val reason=category(error);event(stage,reason);throw ConfigurationFailure(stage,reason)}
    }
}
internal class ConfigurationFailure(val stage:ConfigurationDiagnostic.Stage,val reason:ConfigurationDiagnostic.Reason):
    IllegalStateException("configuration stage failed")

/** Independent phase/terminal/operation reservations INSIDE the original256-row cap. */
internal class ConfigurationEventBudget(configurationOnly:Boolean) {
    private val general=AtomicInteger(if(configurationOnly)64 else 160)
    private val configuration=if(configurationOnly)AtomicInteger(96) else null
    private fun admit(counter:AtomicInteger)=counter.getAndUpdate { if(it>0)it-1 else 0 }>0
    private val critical=AtomicInteger(16)
    private val operation=AtomicInteger(32)
    private val phase=AtomicInteger(48)
    fun critical()=admit(critical)
    fun operation()=admit(operation)
    fun phase()=admit(phase)
    fun general()=admit(general)
    fun configuration()=admit(configuration?:general)
}
