package com.littlebuddy.v2.parent

import java.util.concurrent.atomic.AtomicInteger

/** Closed vocabulary only. No authentication data or exception text can enter this port.
 * Disabled by default. The diagnostic adapter must be nonblocking; all failures are isolated. */
internal object PinDiagnostic {
    enum class Stage { PROMPT, TAKE, APPROVE, RECEIPT, PAGE, TICK, SAVE, CONSUME, DERIVE, COMMIT, RESULT, RENDER }
    enum class Reason { BEGIN, SUCCESS, REJECTED, ERROR, MISSING, EXPIRED, NO_FOCUS, CANCEL,
        INVALIDATED, TICK_OWNER_INVALID, SAVE_IN_PROGRESS, EARLY_REJECT, CHALLENGE_REJECT,
        PIN_MISMATCH, STALE_CALLBACK, UNOWNED, LOCKED, AUTHORIZED, COOLDOWN, QUARANTINED,
        SECURITY_ERROR, IO_ERROR, STATE_ERROR, OTHER_ERROR }
    private val sequence = AtomicInteger()
    @Volatile private var sink: ((Int, Long, Stage, Reason) -> Unit)? = null
    fun install(adapter: ((Int, Long, Stage, Reason) -> Unit)?) { sink = adapter }
    fun begin() { if (sink != null) { sequence.incrementAndGet(); event(Stage.PROMPT, Reason.BEGIN) } }
    fun event(stage: Stage, reason: Reason) {
        try { sink?.invoke(sequence.get(), System.nanoTime() / 1_000_000, stage, reason) }
        catch (_: Throwable) { /* Observability must never affect authorization. */ }
    }
    fun error(stage: Stage, error: Exception) = event(stage, when (error) {
        is java.security.GeneralSecurityException -> Reason.SECURITY_ERROR
        is java.io.IOException -> Reason.IO_ERROR
        is IllegalStateException -> Reason.STATE_ERROR
        else -> Reason.OTHER_ERROR
    })
}
