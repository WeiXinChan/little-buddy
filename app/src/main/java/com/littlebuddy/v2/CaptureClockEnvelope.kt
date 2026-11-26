package com.littlebuddy.v2

/** Finite capture-time model, NOT an AudioTimestamp accuracy guarantee.
 * True time at each hardware frame must be within +/-0.5ms of its estimate, with a path whose
 * rate stays 15984..16016Hz. Reachable intervals propagate; observations never reset that path.
 * Additionally every raw pair >=500ms retains the original rate +/-2-frame long-window oracle.
 */
internal class CaptureClockEnvelope {
    companion object {
        const val PHASE_NS=500_000L
        const val LONG_NS=500_000_000L
        private const val MIN=15984L
        private const val MAX=16016L
        private const val BILLION=1_000_000_000L
        private const val TWO_FRAMES=2*BILLION
        // At most ~8025 distinct advancing frames in 0.5s under the model. No unbounded history.
        private const val MAX_PENDING=8192
    }
    private var last:CaptureStamp?=null
    private var first:CaptureStamp?=null
    private var low=0L
    private var high=0L
    private data class Point(val ns:Long,val lower:Long,val upper:Long)
    private val pending=java.util.ArrayDeque<Point>()
    private var maximumLower:Long?=null
    private var minimumUpper:Long?=null
    // Admission may narrow lo, but resource/age accounting never refunds the phase reserve.
    // This outer bound is conservative even when several observations constrain a tighter path.
    val earliestNs get()=checkNotNull(last).nanoTime-PHASE_NS
    fun observe(candidate:CaptureStamp) {
        val old=last
        if(old==candidate)return
        var nextLow=candidate.nanoTime-PHASE_NS
        var nextHigh=Math.addExact(candidate.nanoTime,PHASE_NS)
        if(old!=null){
            val df=candidate.frames-old.frames
            check(df>0 && candidate.nanoTime>old.nanoTime){"capture timestamp regressed"}
            val nanos=df*BILLION
            nextLow=maxOf(nextLow,Math.addExact(low,nanos/MAX))
            nextHigh=minOf(nextHigh,Math.addExact(high,(nanos+MIN-1)/MIN))
            check(nextLow<=nextHigh){"capture phase/rate model exhausted"}
        }
        val origin=first ?: candidate
        val df=candidate.frames-origin.frames;val dn=candidate.nanoTime-origin.nanoTime
        check(df>=0 && dn>=0 && dn<=(Long.MAX_VALUE-TWO_FRAMES)/MAX){"capture clock model range"}
        val lower=df*BILLION-dn*MIN;val upper=df*BILLION-dn*MAX
        while(pending.isNotEmpty() && candidate.nanoTime-pending.first.ns>=LONG_NS){
            val p=pending.removeFirst()
            maximumLower=maximumLower?.let{maxOf(it,p.lower)} ?: p.lower
            minimumUpper=minimumUpper?.let{minOf(it,p.upper)} ?: p.upper
        }
        // Aggregated extrema check ALL eligible historical pairs, not just one rolling anchor.
        maximumLower?.let{check(lower>=it-TWO_FRAMES){"capture long rate outside bound"}}
        minimumUpper?.let{check(upper<=it+TWO_FRAMES){"capture long rate outside bound"}}
        check(pending.size<MAX_PENDING){"capture clock history exhausted"}
        pending.addLast(Point(candidate.nanoTime,lower,upper))
        first=origin;last=candidate;low=nextLow;high=nextHigh
    }
}
