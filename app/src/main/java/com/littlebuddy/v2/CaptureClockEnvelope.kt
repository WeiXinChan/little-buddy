package com.littlebuddy.v2

/** Finite capture-time model, NOT an AudioTimestamp accuracy guarantee.
 * True time at each hardware frame must be within +/-2ms of its estimate, with a path whose
 * rate stays 15984..16016Hz. Reachable intervals propagate; observations never reset that path.
 * Every pair >=500ms keeps the same rate interval and +/-2-frame allowance, with both
 * endpoint phase uncertainties propagated into the raw-pair time bound (not a new rate).
 */
internal class CaptureClockEnvelope(private val report:(CaptureClockFailure)->Unit=CaptureClockDiagnostic::emit) {
    companion object {
        const val PHASE_NS=2_000_000L
        const val STARTUP_PHASE_NS=500_000L
        const val LONG_NS=500_000_000L
        private const val MIN=15984L
        private const val MAX=16016L
        private const val BILLION=1_000_000_000L
        private const val TWO_FRAMES=2*BILLION
        internal const val LOWER_BUDGET=TWO_FRAMES+2*PHASE_NS*MIN
        internal const val UPPER_BUDGET=TWO_FRAMES+2*PHASE_NS*MAX
        // At most ~8025 distinct advancing frames in 0.5s under the model. No unbounded history.
        private const val MAX_PENDING=8192
    }
    private var phaseNs=PHASE_NS
    fun beginStartup() {check(last==null);phaseNs=STARTUP_PHASE_NS}
    fun finishStartup() {phaseNs=PHASE_NS} // One bounded expansion, no path/history reset.
    private var last:CaptureStamp?=null
    private var first:CaptureStamp?=null
    private var low=0L
    private var high=0L
    private data class Point(val frames:Long,val ns:Long,val lower:Long,val upper:Long)
    private val pending=java.util.ArrayDeque<Point>()
    private var maximumLower:Point?=null
    private var minimumUpper:Point?=null
    private var reportedRawRejection=false
    // Admission may narrow lo, but resource/age accounting never refunds the phase reserve.
    // This outer bound is conservative even when several observations constrain a tighter path.
    val earliestNs get()=checkNotNull(last).nanoTime-phaseNs
    fun observe(candidate:CaptureStamp) {
        if(last==candidate)return
        if(candidate.frames==0L){
            // No captured frame yet: preserve the observation for age/room, but it cannot anchor
            // a capture-rate path. Startup still needs two positive pairs and sample0 proof.
            last=candidate;return
        }
        val old=last?.takeIf{it.frames>0}
        var nextLow=candidate.nanoTime-phaseNs
        var nextHigh=Math.addExact(candidate.nanoTime,phaseNs)
        if(old!=null){
            val df=candidate.frames-old.frames
            clockCheck(df>0 && candidate.nanoTime>old.nanoTime,CaptureClockReason.TIMESTAMP_REGRESSED)
            val nanos=df*BILLION
            nextLow=maxOf(nextLow,Math.addExact(low,nanos/MAX))
            nextHigh=minOf(nextHigh,Math.addExact(high,(nanos+MIN-1)/MIN))
            clockCheck(nextLow<=nextHigh,CaptureClockReason.PHASE_RATE_MODEL_EXHAUSTED)
        }
        val origin=first ?: candidate
        val df=candidate.frames-origin.frames;val dn=candidate.nanoTime-origin.nanoTime
        clockCheck(df>=0 && dn>=0 && dn<=(Long.MAX_VALUE-UPPER_BUDGET)/MAX,CaptureClockReason.CLOCK_MODEL_RANGE)
        val lower=df*BILLION-dn*MIN;val upper=df*BILLION-dn*MAX
        while(pending.isNotEmpty() && candidate.nanoTime-pending.first.ns>=LONG_NS){
            val p=pending.removeFirst()
            maximumLower=maximumLower?.takeIf{it.lower>=p.lower} ?: p
            minimumUpper=minimumUpper?.takeIf{it.upper<=p.upper} ?: p
        }
        // Aggregated extrema check ALL eligible historical pairs, not just one rolling anchor.
        fun witness(p:Point)=CaptureLongWitness(p.frames,p.ns,candidate.frames,candidate.nanoTime,LOWER_BUDGET,UPPER_BUDGET)
        maximumLower?.let {
            if(lower<it.lower-LOWER_BUDGET)throw CaptureClockFailure(CaptureClockReason.LONG_RATE_OUTSIDE_BOUND,longWitness=witness(it))
        }
        minimumUpper?.let {
            if(upper>it.upper+UPPER_BUDGET)throw CaptureClockFailure(CaptureClockReason.LONG_RATE_OUTSIDE_BOUND,longWitness=witness(it))
        }
        // A single opt-in metadata witness per model explains old-oracle false rejection.
        // This certifies only model feasibility, never KWS/upload/native continuity admission.
        if(!reportedRawRejection) {
            val p=maximumLower?.takeIf{lower<it.lower-TWO_FRAMES}
                ?: minimumUpper?.takeIf{upper>it.upper+TWO_FRAMES}
            if(p!=null) {
                reportedRawRejection=true
                try {report(CaptureClockFailure(CaptureClockReason.LONG_RAW_REJECT_PHASE_FEASIBLE,longWitness=witness(p)))}catch(_:Throwable){}
            }
        }
        clockCheck(pending.size<MAX_PENDING,CaptureClockReason.CLOCK_HISTORY_EXHAUSTED)
        pending.addLast(Point(candidate.frames,candidate.nanoTime,lower,upper))
        first=origin;last=candidate;low=nextLow;high=nextHigh
    }
}
