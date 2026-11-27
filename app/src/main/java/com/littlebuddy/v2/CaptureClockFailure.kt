package com.littlebuddy.v2

/** Only fixed predicates and content-free counters; never audio, tokens or exception text. */
internal enum class CaptureClockReason(val legacy: String) {
    STARTUP_DEADLINE("capture startup deadline"),
    STARTUP_NATIVE_CONTINUITY_EXHAUSTED("startup native continuity exhausted"),
    STARTUP_NATIVE_ROOM_EXHAUSTED("startup native room exhausted"),
    STARTUP_SAMPLES_OUTSIDE_BOUND("startup samples outside bound"),
    NATIVE_READ_EXCEEDS_TIMESTAMP_POSITION("native read exceeds timestamp position"),
    STARTUP_ANCHOR_UNCONFIRMED("capture startup anchor unconfirmed"),
    STARTUP_ORIGIN_UNPROVEN("capture startup origin unproven"),
    CLOCK_REGRESSED("capture clock regressed"),
    CLOCK_REGRESSED_DURING_TIMESTAMP("capture clock regressed during timestamp"),
    TIMEBASE_UNCERTAIN("capture timebase measurement uncertain"),
    TIMEBASE_CHANGED("capture timebase changed"),
    INVALID_CAPTURE_TIMESTAMP("invalid capture timestamp"),
    TIMESTAMP_REGRESSED("capture timestamp regressed"),
    TIMESTAMP_RELABELED("capture timestamp relabeled"),
    STARTUP_COUNTER_OUTSIDE_BOUND("capture startup counter outside bound"),
    TIMESTAMP_UNAVAILABLE("capture timestamp unavailable"),
    TIMESTAMP_STALE("capture timestamp stale"),
    CUMULATIVE_NATIVE_CONTINUITY_EXHAUSTED("cumulative native continuity exhausted"),
    CUMULATIVE_NATIVE_ROOM_EXHAUSTED("cumulative native room exhausted"),
    TIMESTAMP_NOT_READY("capture timestamp not ready"),
    PHASE_RATE_MODEL_EXHAUSTED("capture phase/rate model exhausted"),
    CLOCK_MODEL_RANGE("capture clock model range"),
    LONG_RATE_OUTSIDE_BOUND("capture long rate outside bound"),
    CLOCK_HISTORY_EXHAUSTED("capture clock history exhausted"),
    LONG_RAW_REJECT_PHASE_FEASIBLE("raw long oracle rejects phase feasible model"),
    RECORDER_NOT_RECORDING("capture recorder not recording")
}
internal data class CaptureClockEvidence(
    val frames:Long=0, val reads:Long=0, val deltaFrames:Long=0, val deltaNs:Long=0,
    val ageNs:Long=0, val checkGapMs:Long=0, val apiMs:Long=0, val bridgeMs:Long=0,
    val capacity:Int=0,val apiBeforeMs:Long=0,val apiAfterMs:Long=0,val stampNs:Long=0,
    val stampReturned:Boolean=false,val phaseNs:Long=0,val conservativeAgeNs:Long=0,val maxAgeNs:Long=0,val starting:Boolean=false,
    val bridgeOriginBeforeMs:Long=0,val bridgeOriginBootMs:Long=0,val bridgeOriginAfterMs:Long=0,
    val bridgeBeforeMs:Long=0,val bridgeBootMs:Long=0,val bridgeAfterMs:Long=0,
    val bridgeOriginLowerMs:Long=0,val bridgeOriginUpperMs:Long=0,val bridgeLowerMs:Long=0,val bridgeUpperMs:Long=0,
    val bridgeAttempts:Int=0)
internal data class CaptureLongWitness(val fromFrame:Long,val fromNs:Long,val toFrame:Long,val toNs:Long,val lowerBudget:Long,val upperBudget:Long)
internal enum class CaptureReadStep { NONE, STARTUP, PRE_ROOM, AFTER_ROOM, NATIVE_READ, PREFIX_REPLAY, POST_READ, KWS_REARM, POST_REARM, KWS, POST_KWS, UPLOAD_ADMIT, CLEANUP }
internal enum class CaptureTimestampResult { NOT_CALLED, IN_FLIGHT, SUCCESS, UNAVAILABLE, OTHER }
internal data class CaptureClockContext(val activity:Long=0,val transport:Long=0,val capture:Long=0,
    val step:CaptureReadStep=CaptureReadStep.NONE,val cancelled:Boolean=false,val allowed:Boolean=false,
    val stopRequested:Boolean=false,val nativeReleased:Boolean=false,val timestampResult:CaptureTimestampResult=CaptureTimestampResult.NOT_CALLED,
    val lastOperation:Int=0,val operationBeforeNs:Long=0,val operationAfterNs:Long=0)
internal class CaptureClockFailure(val reason:CaptureClockReason,
    val evidence:CaptureClockEvidence=CaptureClockEvidence(),val longWitness:CaptureLongWitness?=null,val context:CaptureClockContext?=null):IllegalStateException(reason.legacy)
internal fun clockCheck(valid:Boolean, reason:CaptureClockReason) {
    if(!valid)throw CaptureClockFailure(reason)
}
internal object CaptureClockDiagnostic {
    @Volatile private var sink:((CaptureClockFailure)->Unit)?=null
    fun install(value:((CaptureClockFailure)->Unit)?) { sink=value }
    fun emit(error:CaptureClockFailure) { try { sink?.invoke(error) } catch(_:Throwable) { } }
}
