package com.littlebuddy.v2.parent

import java.util.concurrent.atomic.AtomicInteger

/** Closed vocabulary only. No authentication data or exception text can enter this port.
 * Disabled by default. The diagnostic adapter must be nonblocking; all failures are isolated. */
internal object PinDiagnostic {
    enum class Stage { PROMPT, TAKE, APPROVE, RECEIPT, PAGE, TICK, SAVE, CONSUME, DERIVE, COMMIT, RESULT, RENDER, CONFIG, SSH, FORWARD, SOCKET, WSS, PROTOCOL, CAPTURE_NATIVE, CAPTURE_MODEL, CAPTURE_STARTUP, CAPTURE_READ, CAPTURE_CLOCK, CAPTURE_QUEUE, CAPTURE_KWS, CAPTURE_CLEANUP, HELP, TECHNICAL }
    enum class Reason { BEGIN, SUCCESS, REJECTED, ERROR, MISSING, EXPIRED, NO_FOCUS, CANCEL,
        INVALIDATED, TICK_OWNER_INVALID, SAVE_IN_PROGRESS, EARLY_REJECT, CHALLENGE_REJECT,
        PIN_MISMATCH, STALE_CALLBACK, UNOWNED, LOCKED, AUTHORIZED, COOLDOWN, QUARANTINED,
        SECURITY_ERROR, IO_ERROR, STATE_ERROR, OTHER_ERROR, TLS_HANDSHAKE, TLS_PEER, SSH_ERROR, TIMEOUT, ARGUMENT_ERROR, READY, SAVED_LOCAL, NO_CONFIG, HOLD, PARENT_RETRY, RETURN, NETWORK, CLOSED, PROTOCOL_FAILED, INCOMPATIBLE, CAPTURE_FAILED, RELEASE_FAILED, TLS_ERROR, AUTH_DENIED, HTTP_FAILED, CONNECT_FAILED, DNS_FAILED }
    private val sequence = AtomicInteger()
    @Volatile private var sink: ((Int, Long, Stage, Reason) -> Unit)? = null
    fun install(adapter: ((Int, Long, Stage, Reason) -> Unit)?) { sink = adapter }
    fun begin() { if (sink != null) { sequence.incrementAndGet(); event(Stage.PROMPT, Reason.BEGIN) } }
    fun beginRuntime() { if (sink != null) { sequence.incrementAndGet(); event(Stage.CONFIG, Reason.BEGIN) } }
    /** Closed exception categories only: never inspect messages, stack traces or response bodies. */
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
                e is java.io.IOException -> Reason.IO_ERROR
                else -> Reason.OTHER_ERROR
            }
            if (reason == Reason.OTHER_ERROR || reason == Reason.IO_ERROR) reason = category
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
