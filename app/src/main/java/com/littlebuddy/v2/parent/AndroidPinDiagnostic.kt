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
                PinDiagnostic.install(null); PinDiagnostic.installRuntime(null); com.littlebuddy.v2.CaptureClockDiagnostic.install(null); queue.clear()
            }, "v2-pin-diag").apply { isDaemon = true }
            writer.start()
            com.littlebuddy.v2.CaptureClockDiagnostic.install { error ->
                val c=error.context
                fun flag(value:Boolean?)=if(value==null)-1 else if(value)1 else 0
                val scope="ctx_known=${c!=null} activity=${c?.activity ?: -1} transport=${c?.transport ?: -1} capture=${c?.capture ?: -1} read_step=${c?.step?.name ?: "NONE"} cancelled=${flag(c?.cancelled)} allowed=${flag(c?.allowed)} stop_requested=${flag(c?.stopRequested)} native_released=${flag(c?.nativeReleased)} timestamp_result=${c?.timestampResult?.name ?: "NOT_CALLED"}"
                val w=error.longWitness
                if(w!=null && remaining.getAndDecrement()>0) {
                    queue.offer("mono_ms=${System.nanoTime()/1_000_000} stage=CAPTURE_LONG_PAIR reason=${error.reason.name} from_frame=${w.fromFrame} from_ns=${w.fromNs} to_frame=${w.toFrame} to_ns=${w.toNs} df=${w.toFrame-w.fromFrame} dn_ns=${w.toNs-w.fromNs} lower_budget=${w.lowerBudget} upper_budget=${w.upperBudget} phase_ns=2000000 min_rate=15984 max_rate=16016 $scope")
                }
                if(error.reason!=com.littlebuddy.v2.CaptureClockReason.LONG_RAW_REJECT_PHASE_FEASIBLE && remaining.getAndDecrement()>0) {
                    val e=error.evidence
                    queue.offer("mono_ms=${System.nanoTime()/1_000_000} stage=CAPTURE_CLOCK_DETAIL reason=${error.reason.name} frames=${e.frames} reads=${e.reads} df=${e.deltaFrames} dn_ns=${e.deltaNs} age_ns=${e.ageNs} check_gap_ms=${e.checkGapMs} api_ms=${e.apiMs} bridge_ms=${e.bridgeMs} capacity=${e.capacity} api_before_ms=${e.apiBeforeMs} api_after_ms=${e.apiAfterMs} stamp_ns=${e.stampNs} stamp_returned=${e.stampReturned} phase_ns=${e.phaseNs} conservative_age_ns=${e.conservativeAgeNs} max_age_ns=${e.maxAgeNs} starting=${e.starting} bridge_origin_before_ms=${e.bridgeOriginBeforeMs} bridge_origin_boot_ms=${e.bridgeOriginBootMs} bridge_origin_after_ms=${e.bridgeOriginAfterMs} bridge_before_ms=${e.bridgeBeforeMs} bridge_boot_ms=${e.bridgeBootMs} bridge_after_ms=${e.bridgeAfterMs} bridge_origin_lower_ms=${e.bridgeOriginLowerMs} bridge_origin_upper_ms=${e.bridgeOriginUpperMs} bridge_lower_ms=${e.bridgeLowerMs} bridge_upper_ms=${e.bridgeUpperMs} bridge_attempts=${e.bridgeAttempts} $scope")
                }
            }
            PinDiagnostic.installRuntime { event ->
                if(remaining.getAndDecrement()>0) {
                    val c=event.scope
                    val detail=when(event.stage) {
                        PinDiagnostic.RuntimeStage.CAPTURE_START,PinDiagnostic.RuntimeStage.CAPTURE_CANCEL,
                        PinDiagnostic.RuntimeStage.CAPTURE_STOP_BEGIN,PinDiagnostic.RuntimeStage.CAPTURE_STOP_END,
                        PinDiagnostic.RuntimeStage.CAPTURE_FAILURE,PinDiagnostic.RuntimeStage.CAPTURE_RELEASE,
                        PinDiagnostic.RuntimeStage.WORKER_JOINED -> "operation=${event.operation.name} cancelled=${event.cancelled} allowed=${event.allowed} stop_requested=${event.stopRequested} native_released=${event.nativeReleased} worker_joined=${event.workerJoined}"
                        PinDiagnostic.RuntimeStage.FAILURE_UI_APPLY,PinDiagnostic.RuntimeStage.FAILURE_UI_RETIRED -> "current_transport=${event.currentTransport} current_capture=${event.currentCapture}"
                        PinDiagnostic.RuntimeStage.ACTIVITY_CREATE -> "restored=${event.restored} launcher=${event.launcher}"
                        PinDiagnostic.RuntimeStage.ACTIVITY_NEW_INTENT -> "launcher=${event.launcher}"
                        else -> ""
                    }
                    queue.offer("mono_ms=${System.nanoTime()/1_000_000} stage=RUNTIME_${event.stage.name} source=${event.source.name} activity=${c.activity} transport=${c.transport} capture=${c.capture} scope_known=${c.activity>0} wire=${event.wire.name} point=${event.point.name} $detail")
                }
            }
            PinDiagnostic.install { seq, ms, stage, reason ->
                if (remaining.getAndDecrement() > 0)
                    queue.offer("flow=$seq mono_ms=$ms stage=${stage.name} reason=${reason.name}")
            }
        } catch (_: Throwable) { PinDiagnostic.install(null); PinDiagnostic.installRuntime(null); com.littlebuddy.v2.CaptureClockDiagnostic.install(null) }
    }
}
