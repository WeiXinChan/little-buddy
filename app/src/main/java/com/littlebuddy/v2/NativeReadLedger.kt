package com.littlebuddy.v2

internal data class CaptureStamp(val frames:Long,val nanoTime:Long)

/** Cumulative hardware capture position minus cumulative successful reads. Never rebases on read.
 * Timestamp estimates use CaptureClockEnvelope; age/extrapolation remains <=100ms.
 * Phase uncertainty and 1ms clock quantization are charged to produced upper and sample age.
 * A missing/stale/regressing/incoherent timestamp fails closed; no unbounded software fallback.
 */
internal class NativeReadLedger(private val capacity:Int,private val mono:()->Long,
    private val boot:()->Long,private val stamp:()->CaptureStamp?) {
    companion object {
        const val MODEL="startup500us-runtime2ms-long500ms-v3"
        const val STARTUP_LIMIT_MS=500L
        const val STARTUP_SAMPLES=8000
        const val MIN_RATE=15984L
        private const val MAX_RATE=16016L
        fun durationMs(samples:Long)=(samples*1000+MIN_RATE-1)/MIN_RATE
    }
    private val bridge=CaptureClockBridge(mono,boot)
    private val monoOrigin=bridge.origin.after
    // Earliest BOOTTIME mapping, including the unchanged 5ms admissible bridge displacement.
    private val bootOrigin=bridge.earliestBoot(monoOrigin)
    private val reserve=320L
    private val startupMs=(capacity-reserve)/16
    private val maxAgeNs=minOf(100L,startupMs)*1_000_000
    private var checkedAt=monoOrigin
    private var observed:CaptureStamp?=null
    private var report:(CaptureClockFailure)->Unit=CaptureClockDiagnostic::emit
    private val clock=CaptureClockEnvelope {report(it)}
    /** Install only before native start; observation carries no authority or timestamp renewal. */
    fun diagnostics(value:(CaptureClockFailure)->Unit) {report=value}
    fun diagnosticEvidence()=evidence()
    private var attempted:CaptureStamp?=null
    private var previous:CaptureStamp?=null
    private var gapMs=0L
    private var apiMs=0L
    private var apiBeforeMs=monoOrigin
    private var apiAfterMs=monoOrigin
    private var bridgeMs=0L
    private var evidenceTime=monoOrigin
    private fun difference(a:Long,b:Long)=try { Math.subtractExact(a,b) } catch(_:ArithmeticException) { 0L }
    private fun evidence():CaptureClockEvidence {
        val value=attempted ?: observed
        return CaptureClockEvidence(value?.frames ?: 0,readSamples,
            if(value!=null && previous!=null)difference(value.frames,previous!!.frames) else 0,
            if(value!=null && previous!=null)difference(value.nanoTime,previous!!.nanoTime) else 0,
            if(value!=null)difference(evidenceTime*1_000_000,value.nanoTime) else 0,
            gapMs,apiMs,bridgeMs,capacity,apiBeforeMs,apiAfterMs,value?.nanoTime ?: 0,attempted!=null,
            if(starting)CaptureClockEnvelope.STARTUP_PHASE_NS else CaptureClockEnvelope.PHASE_NS,
            if(value!=null)(evidenceTime+1)*1_000_000-(value.nanoTime-(if(starting)CaptureClockEnvelope.STARTUP_PHASE_NS else CaptureClockEnvelope.PHASE_NS)) else 0,
            maxAgeNs,starting,bridge.origin.before,bridge.origin.boot,bridge.origin.after,
            bridge.last.before,bridge.last.boot,bridge.last.after,bridge.origin.lower,bridge.origin.upper,
            bridge.last.lower,bridge.last.upper,bridge.attempts)
    }
    private fun guard(valid:Boolean,reason:CaptureClockReason) {
        if(!valid)throw CaptureClockFailure(reason,evidence())
    }
    private var startupOrigin=monoOrigin
    private var nativeStartArmed=false
    private var starting=false
    private var startupPairs=0
    val startupAnchored get()=starting && startupPairs>=2
    fun beginStartup() {check(!starting && observed==null && readSamples==0L);clock.beginStartup();starting=true}
    /** One boundary BEFORE native start, after allocations/admission. Never reset after JNI.
     * The whole unknown start/JNI interval still counts as potentially producing samples. */
    fun armNativeStart():Long {
        check(starting && !nativeStartArmed && observed==null && readSamples==0L)
        val time=mono();guard(time>=checkedAt,CaptureClockReason.CLOCK_REGRESSED)
        nativeStartArmed=true;startupOrigin=time;checkedAt=time;evidenceTime=time
        return time
    }
    private fun softwareUpper(time:Long)=((time-startupOrigin+1)*MAX_RATE+999)/1000
    private fun softwareRoom(time:Long):Long {
        guard(time-startupOrigin<STARTUP_LIMIT_MS,CaptureClockReason.STARTUP_DEADLINE)
        val left=capacity-reserve-maxOf(0,softwareUpper(time)-readSamples)
        guard(left>0,CaptureClockReason.STARTUP_NATIVE_CONTINUITY_EXHAUSTED)
        val room=left*1000/MAX_RATE
        guard(room>0,CaptureClockReason.STARTUP_NATIVE_ROOM_EXHAUSTED)
        return minOf(room,STARTUP_LIMIT_MS-(time-startupOrigin))
    }
    fun stageRead(count:Int) {
        require(count>=0);check(starting)
        remainingMs() // Charge all read/JNI delay before accounting newly returned data.
        val total=readSamples+count
        guard(total<=STARTUP_SAMPLES && total<=softwareUpper(checkedAt),CaptureClockReason.STARTUP_SAMPLES_OUTSIDE_BOUND)
        observed?.let { value ->
            guard(total<=producedUpper(value,checkedAt),CaptureClockReason.NATIVE_READ_EXCEEDS_TIMESTAMP_POSITION)
        }
        readSamples=total
    }
    fun finishStartup() {
        remainingMs();guard(startupAnchored,CaptureClockReason.STARTUP_ANCHOR_UNCONFIRMED)
        guard(sampleTime(0)>=bootOrigin-2,CaptureClockReason.STARTUP_ORIGIN_UNPROVEN)
        starting=false
        clock.finishStartup() // Retain established startup path and sample origin; spend larger phase reserve thereafter.
    }
    var readSamples=0L;private set
    val ready get()=observed!=null
    fun clockModel()=MODEL
    init {require(capacity>reserve && startupMs>0)}
    private fun refresh():Pair<CaptureStamp?,Long> = try { refreshChecked() }
    catch(error:CaptureClockFailure) { throw CaptureClockFailure(error.reason,evidence(),error.longWitness) }
    private fun refreshChecked():Pair<CaptureStamp?,Long> {
        val before=mono()
        apiBeforeMs=before; previous=observed; attempted=null; gapMs=difference(before,checkedAt); apiMs=0
        evidenceTime=before
        guard(before>=checkedAt && before>=monoOrigin,CaptureClockReason.CLOCK_REGRESSED)
        val candidate=stamp() // JNI/provider time belongs to this same budget, never to the next read.
        attempted=candidate
        apiAfterMs=mono();apiMs=difference(apiAfterMs,before);evidenceTime=apiAfterMs
        guard(apiAfterMs>=before,CaptureClockReason.CLOCK_REGRESSED_DURING_TIMESTAMP)
        // Boot reads are not atomic with mono reads. Bound both sampling windows. At most one
        // additional measurement may resolve a scheduling-wide window; every elapsed ms is charged.
        try {bridge.check(apiAfterMs)} finally {
            evidenceTime=bridge.last.after
            bridgeMs=bridge.last.boot-bridge.origin.boot-(bridge.last.before-bridge.origin.after)
        }
        val time=bridge.last.after
        checkedAt=time
        if(starting)softwareRoom(time)
        if(candidate!=null) {
            guard(candidate.frames in 0..(Long.MAX_VALUE/1_000_000_000) && candidate.nanoTime>=0 && candidate.nanoTime<=time*1_000_000+1_000_000,CaptureClockReason.INVALID_CAPTURE_TIMESTAMP)
            val old=observed
            if(old!=null) {
                guard(candidate.frames>=old.frames && candidate.nanoTime>=old.nanoTime,CaptureClockReason.TIMESTAMP_REGRESSED)
                // A stationary frame must not be made fresh by changing its timestamp.
                guard(candidate.frames!=old.frames || candidate.nanoTime==old.nanoTime,CaptureClockReason.TIMESTAMP_RELABELED)
            }
            clock.observe(candidate)
            if(starting) {
                guard(candidate.frames<=softwareUpper(time),CaptureClockReason.STARTUP_COUNTER_OUTSIDE_BOUND)
                val origin=clock.earliestNs-Math.floorDiv(candidate.frames*1_000_000_000+MIN_RATE-1,MIN_RATE)
                guard(origin>=startupOrigin*1_000_000-1_000_000,CaptureClockReason.STARTUP_ORIGIN_UNPROVEN)
                if(candidate.frames>0) {
                    if(old==null || old.frames==0L)startupPairs=1
                    else if(candidate.frames>old.frames)startupPairs++
                }
            }
            observed=candidate
        }
        val value=observed
        if(value==null && !starting)guard(time-monoOrigin<startupMs,CaptureClockReason.TIMESTAMP_UNAVAILABLE)
        else if(value!=null){
            guard((time+1)*1_000_000-clock.earliestNs<=maxAgeNs,CaptureClockReason.TIMESTAMP_STALE)
            // A new estimate may shrink the frontier. Reject before prefix/KWS admission, not
            // merely on the next read; max(0, upper-read) must never hide inconsistent history.
            guard(readSamples<=producedUpper(value,time),CaptureClockReason.NATIVE_READ_EXCEEDS_TIMESTAMP_POSITION)
        }
        return value to time
    }
    private fun producedUpper(value:CaptureStamp,time:Long):Long {
        // mono() is floor milliseconds; account for its whole 1ms bin, plus the model's earliest
        // possible capture time. Uncertainty always spends native room, never refreshes the budget.
        val lag=maxOf(0,(time+1)*1_000_000-clock.earliestNs)
        return value.frames+(lag*MAX_RATE+999_999_999)/1_000_000_000
    }
    fun remainingMs():Long {
        val (value,time)=refresh()
        if(value==null)return if(starting)softwareRoom(time) else startupMs-(time-monoOrigin)
        val produced=producedUpper(value,time)
        val unread=maxOf(0,produced-readSamples)
        val left=capacity-reserve-unread
        guard(left>0,CaptureClockReason.CUMULATIVE_NATIVE_CONTINUITY_EXHAUSTED)
        val room=left*1000/MAX_RATE
        guard(room>0,CaptureClockReason.CUMULATIVE_NATIVE_ROOM_EXHAUSTED)
        return if(starting)minOf(room,softwareRoom(time)) else room
    }
    fun check(){remainingMs();guard(ready,CaptureClockReason.TIMESTAMP_NOT_READY)}
    fun read(count:Int):Long {
        require(count>=0);check()
        val value=checkNotNull(observed)
        val upper=producedUpper(value,checkedAt)
        val total=readSamples+count
        guard(total<=upper,CaptureClockReason.NATIVE_READ_EXCEEDS_TIMESTAMP_POSITION)
        readSamples=total
        return sampleTime(total)
    }
    fun sampleTime(position:Long):Long {
        require(position in 0..readSamples)
        val value=checkNotNull(observed)
        val delta=position-value.frames
        val rate=if(delta<0)MIN_RATE else MAX_RATE
        // Earliest feasible model time (including phase uncertainty), and 1ms bridge rounding.
        val nativeNs=clock.earliestNs+Math.floorDiv(delta*1_000_000_000,rate)
        return bridge.earliestBoot(Math.floorDiv(nativeNs,1_000_000))-1
    }
}

/** Bracket BOOTTIME with MONOTONIC. Both callbacks return floor milliseconds.
 * For m0 <= actual mono at boot read < m1+1, offset is in [b-m1-1,b-m0+1].
 * No point estimate can remove scheduling uncertainty. An unresolved window fails closed.
 */
internal class CaptureClockBridge(private val mono:()->Long,private val boot:()->Long) {
    companion object {const val LIMIT_MS=5L;private const val ATTEMPTS=2}
    internal data class Window(val before:Long,val boot:Long,val after:Long) {
        val lower get()=boot-after-1
        val upper get()=boot-before+1
    }
    var last=Window(0,0,0);private set
    var attempts=0;private set
    val origin:Window
    init {
        var selected:Window?=null;var floor:Long?=null
        for(i in 1..ATTEMPTS){
            val w=sample(floor);floor=w.after
            if(w.upper-w.lower<=3){selected=w;break}
        }
        origin=selected ?: throw CaptureClockFailure(CaptureClockReason.TIMEBASE_UNCERTAIN,
            CaptureClockEvidence(bridgeBeforeMs=last.before,bridgeBootMs=last.boot,
                bridgeAfterMs=last.after,bridgeLowerMs=last.lower,bridgeUpperMs=last.upper,bridgeAttempts=attempts))
    }
    private fun sample(notBefore:Long?=null):Window {
        val a=mono();val b=boot();val c=mono();last=Window(a,b,c);attempts++
        clockCheck(a>=0 && b>=0 && c>=a && (notBefore==null || a>=notBefore),CaptureClockReason.CLOCK_REGRESSED)
        return last
    }
    fun check(notBefore:Long) {
        attempts=0;var floor=notBefore
        for(i in 1..ATTEMPTS){
            val w=sample(floor);floor=w.after
            val low=w.lower-origin.upper;val high=w.upper-origin.lower
            // Every offset compatible with the observations must be within the original 5ms.
            if(low>=-LIMIT_MS && high<=LIMIT_MS)return
            if(low>LIMIT_MS || high< -LIMIT_MS)throw CaptureClockFailure(CaptureClockReason.TIMEBASE_CHANGED)
        }
        throw CaptureClockFailure(CaptureClockReason.TIMEBASE_UNCERTAIN)
    }
    // Never move an audio timestamp forward using the latest BOOTTIME observation.
    fun earliestBoot(monoMs:Long)=monoMs+origin.lower-LIMIT_MS
}
