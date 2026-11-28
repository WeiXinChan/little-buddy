package com.littlebuddy.v2

import java.util.concurrent.atomic.AtomicBoolean

/** Technical failure is not child safety content. Hold across lifecycle/help-return callbacks;
 * a deliberate parent exit or completed typed recovery-wake handoff restores startup. */
internal class RuntimeRetryGate {
    private val held = AtomicBoolean(false)
    val automaticAllowed get() = !held.get()
    fun technicalFailure() = held.compareAndSet(false, true)
    fun recoverySucceeded(grant:RecoveryEpisode.RecoveryWakeGrant) { held.set(false) }
    fun explicitParentRetry() { held.set(false) }
}

/** Re-evaluated on the UI queue, never cached across owner->UI dispatch or IO. */
internal object CaptureFailureGate {
    fun current(expectedTransport:Long,expectedCapture:Long,currentTransport:Long,currentCapture:Long,permitted:Boolean)=
        expectedTransport==currentTransport && expectedCapture==currentCapture && permitted
}
