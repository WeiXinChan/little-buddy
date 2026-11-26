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
