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
    private val bootOrigin=boot() // BOOT before MONOTONIC: conservative earliest clock bridge
    private val monoOrigin=mono()
    private val reserve=320L
    private val startupMs=(capacity-reserve)/16
    private val maxAgeNs=minOf(100L,startupMs)*1_000_000
    private var checkedAt=monoOrigin
    private var observed:CaptureStamp?=null
    private val clock=CaptureClockEnvelope()
    private var attempted:CaptureStamp?=null
    private var previous:CaptureStamp?=null
    private var gapMs=0L
    private var apiMs=0L
    private var bridgeMs=0L
    private var evidenceTime=monoOrigin
    private fun difference(a:Long,b:Long)=try { Math.subtractExact(a,b) } catch(_:ArithmeticException) { 0L }
    private fun evidence():CaptureClockEvidence {
        val value=attempted ?: observed
        return CaptureClockEvidence(value?.frames ?: 0,readSamples,
            if(value!=null && previous!=null)difference(value.frames,previous!!.frames) else 0,
            if(value!=null && previous!=null)difference(value.nanoTime,previous!!.nanoTime) else 0,
            if(value!=null)difference(evidenceTime*1_000_000,value.nanoTime) else 0,
            gapMs,apiMs,bridgeMs,capacity)
    }
    private fun guard(valid:Boolean,reason:CaptureClockReason) {
        if(!valid)throw CaptureClockFailure(reason,evidence())
    }
    private var starting=false
    private var startupPairs=0
    val startupAnchored get()=starting && startupPairs>=2
    fun beginStartup() {check(!starting && observed==null && readSamples==0L);clock.beginStartup();starting=true}
    private fun softwareUpper(time:Long)=((time-monoOrigin+1)*MAX_RATE+999)/1000
    private fun softwareRoom(time:Long):Long {
        guard(time-monoOrigin<STARTUP_LIMIT_MS,CaptureClockReason.STARTUP_DEADLINE)
        val left=capacity-reserve-maxOf(0,softwareUpper(time)-readSamples)
        guard(left>0,CaptureClockReason.STARTUP_NATIVE_CONTINUITY_EXHAUSTED)
        val room=left*1000/MAX_RATE
        guard(room>0,CaptureClockReason.STARTUP_NATIVE_ROOM_EXHAUSTED)
        return minOf(room,STARTUP_LIMIT_MS-(time-monoOrigin))
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
        previous=observed; attempted=null; gapMs=difference(before,checkedAt); apiMs=0
        evidenceTime=before
        guard(before>=checkedAt && before>=monoOrigin,CaptureClockReason.CLOCK_REGRESSED)
        val candidate=stamp() // JNI/provider time belongs to this same budget, never to the next read.
        attempted=candidate
        val time=mono();val elapsed=boot()-bootOrigin
        evidenceTime=time;apiMs=difference(time,before);bridgeMs=elapsed-(time-monoOrigin)
        guard(time>=before,CaptureClockReason.CLOCK_REGRESSED_DURING_TIMESTAMP)
        guard(kotlin.math.abs(elapsed-(time-monoOrigin))<=5,CaptureClockReason.TIMEBASE_CHANGED)
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
                guard(origin>=monoOrigin*1_000_000-1_000_000,CaptureClockReason.STARTUP_ORIGIN_UNPROVEN)
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
        return bootOrigin+Math.floorDiv(nativeNs-monoOrigin*1_000_000,1_000_000)-1
    }
}
