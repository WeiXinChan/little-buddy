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
        const val MODEL="phase500us-long500ms-v1"
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
    private var starting=false
    private var startupPairs=0
    val startupAnchored get()=starting && startupPairs>=2
    fun beginStartup() {check(!starting && observed==null && readSamples==0L);starting=true}
    private fun softwareUpper(time:Long)=((time-monoOrigin+1)*MAX_RATE+999)/1000
    private fun softwareRoom(time:Long):Long {
        check(time-monoOrigin<STARTUP_LIMIT_MS){"capture startup deadline"}
        val left=capacity-reserve-maxOf(0,softwareUpper(time)-readSamples)
        check(left>0){"startup native continuity exhausted"}
        val room=left*1000/MAX_RATE
        check(room>0){"startup native room exhausted"}
        return minOf(room,STARTUP_LIMIT_MS-(time-monoOrigin))
    }
    fun stageRead(count:Int) {
        require(count>=0);check(starting)
        remainingMs() // Charge all read/JNI delay before accounting newly returned data.
        val total=readSamples+count
        check(total<=STARTUP_SAMPLES && total<=softwareUpper(checkedAt)){"startup samples outside bound"}
        observed?.let { value ->
            check(total<=producedUpper(value,checkedAt)){"native read exceeds timestamp position"}
        }
        readSamples=total
    }
    fun finishStartup() {
        remainingMs();check(startupAnchored){"capture startup anchor unconfirmed"}
        check(sampleTime(0)>=bootOrigin-2){"capture startup origin unproven"}
        starting=false
    }
    var readSamples=0L;private set
    val ready get()=observed!=null
    fun clockModel()=MODEL
    init {require(capacity>reserve && startupMs>0)}
    private fun refresh():Pair<CaptureStamp?,Long> {
        val before=mono()
        check(before>=checkedAt && before>=monoOrigin){"capture clock regressed"}
        val candidate=stamp() // JNI/provider time belongs to this same budget, never to the next read.
        val time=mono();val elapsed=boot()-bootOrigin
        check(time>=before){"capture clock regressed during timestamp"}
        check(kotlin.math.abs(elapsed-(time-monoOrigin))<=5){"capture timebase changed"}
        checkedAt=time
        if(starting)softwareRoom(time)
        if(candidate!=null) {
            check(candidate.frames in 0..(Long.MAX_VALUE/1_000_000_000) && candidate.nanoTime>=0 && candidate.nanoTime<=time*1_000_000+1_000_000){"invalid capture timestamp"}
            val old=observed
            if(old!=null) {
                check(candidate.frames>=old.frames && candidate.nanoTime>=old.nanoTime){"capture timestamp regressed"}
                // A stationary frame must not be made fresh by changing its timestamp.
                check(candidate.frames!=old.frames || candidate.nanoTime==old.nanoTime){"capture timestamp relabeled"}
            }
            clock.observe(candidate)
            if(starting) {
                check(candidate.frames<=softwareUpper(time)){"capture startup counter outside bound"}
                val origin=clock.earliestNs-Math.floorDiv(candidate.frames*1_000_000_000+MIN_RATE-1,MIN_RATE)
                check(origin>=monoOrigin*1_000_000-1_000_000){"capture startup origin unproven"}
                if(candidate.frames>0) {
                    if(old==null || old.frames==0L)startupPairs=1
                    else if(candidate.frames>old.frames)startupPairs++
                }
            }
            observed=candidate
        }
        val value=observed
        if(value==null && !starting)check(time-monoOrigin<startupMs){"capture timestamp unavailable"}
        else if(value!=null)check((time+1)*1_000_000-clock.earliestNs<=maxAgeNs){"capture timestamp stale"}
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
        check(left>0){"cumulative native continuity exhausted"}
        val room=left*1000/MAX_RATE
        check(room>0){"cumulative native room exhausted"}
        return if(starting)minOf(room,softwareRoom(time)) else room
    }
    fun check(){remainingMs();check(ready){"capture timestamp not ready"}}
    fun read(count:Int):Long {
        require(count>=0);check()
        val value=checkNotNull(observed)
        val upper=producedUpper(value,checkedAt)
        val total=readSamples+count
        check(total<=upper){"native read exceeds timestamp position"}
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
