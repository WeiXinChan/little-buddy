package com.littlebuddy.v2.parent

import android.util.Log
import com.littlebuddy.BuildConfig
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.locks.LockSupport

/** Diagnostic-build-only, process-local, hard capped 256 events. No log IO on auth/UI workers. */
internal object AndroidPinDiagnostic {
    private val started = java.util.concurrent.atomic.AtomicBoolean()
    fun enable() {
        if (!BuildConfig.PIN_INIT_DIAGNOSTICS || !started.compareAndSet(false, true)) return
        try {
            val queue = ConcurrentLinkedQueue<String>()
            val remaining = AtomicInteger(256)
            val writer = Thread({
                // Finite lifetime; dropped events after expiry never accumulate.
                val until = System.nanoTime() + 15L * 60 * 1_000_000_000
                while (System.nanoTime() < until) {
                    val item = queue.poll()
                    if (item == null) LockSupport.parkNanos(100_000_000)
                    else try { Log.i("V2PinInitDiag", item) } catch (_: Throwable) { }
                }
                PinDiagnostic.install(null); com.littlebuddy.v2.CaptureClockDiagnostic.install(null); queue.clear()
            }, "v2-pin-diag").apply { isDaemon = true }
            writer.start()
            com.littlebuddy.v2.CaptureClockDiagnostic.install { error ->
                if(remaining.getAndDecrement()>0) {
                    val e=error.evidence
                    queue.offer("mono_ms=${System.nanoTime()/1_000_000} stage=CAPTURE_CLOCK_DETAIL reason=${error.reason.name} frames=${e.frames} reads=${e.reads} df=${e.deltaFrames} dn_ns=${e.deltaNs} age_ns=${e.ageNs} check_gap_ms=${e.checkGapMs} api_ms=${e.apiMs} bridge_ms=${e.bridgeMs} capacity=${e.capacity}")
                }
            }
            PinDiagnostic.install { seq, ms, stage, reason ->
                if (remaining.getAndDecrement() > 0)
                    queue.offer("flow=$seq mono_ms=$ms stage=${stage.name} reason=${reason.name}")
            }
        } catch (_: Throwable) { PinDiagnostic.install(null); com.littlebuddy.v2.CaptureClockDiagnostic.install(null) }
    }
}
