package com.littlebuddy.v2

import java.util.concurrent.atomic.AtomicBoolean

/** Technical failure is not child safety content. Hold across lifecycle/help-return callbacks;
 * only a deliberate parent exit grants one new automatic startup opportunity. */
internal class RuntimeRetryGate {
    private val held = AtomicBoolean(false)
    val automaticAllowed get() = !held.get()
    fun technicalFailure() = held.compareAndSet(false, true)
    fun explicitParentRetry() { held.set(false) }
}

/** Re-evaluated on the UI queue, never cached across owner->UI dispatch or IO. */
internal object CaptureFailureGate {
    fun current(expectedTransport:Long,expectedCapture:Long,currentTransport:Long,currentCapture:Long,permitted:Boolean)=
        expectedTransport==currentTransport && expectedCapture==currentCapture && permitted
}
