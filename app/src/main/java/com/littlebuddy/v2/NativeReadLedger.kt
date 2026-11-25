package com.littlebuddy.v2

internal data class CaptureStamp(val frames:Long,val nanoTime:Long)

/** Cumulative hardware capture position minus cumulative successful reads. Never rebases on read.
 * Timestamp extrapolation is bounded to <=100ms and +/-1000ppm, not accumulated for the session.
 * A missing/stale/regressing/incoherent timestamp fails closed; no unbounded software fallback.
 */
internal class NativeReadLedger(private val capacity:Int,private val mono:()->Long,
    private val boot:()->Long,private val stamp:()->CaptureStamp?) {
    companion object {
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
    var readSamples=0L;private set
    val ready get()=observed!=null
    init {require(capacity>reserve && startupMs>0)}
    private fun refresh():Pair<CaptureStamp?,Long> {
        val before=mono()
        check(before>=checkedAt && before>=monoOrigin){"capture clock regressed"}
        val candidate=stamp() // JNI/provider time belongs to this same budget, never to the next read.
        val time=mono();val elapsed=boot()-bootOrigin
        check(time>=before){"capture clock regressed during timestamp"}
        check(kotlin.math.abs(elapsed-(time-monoOrigin))<=5){"capture timebase changed"}
        checkedAt=time
        if(candidate!=null) {
            check(candidate.frames in 0..(Long.MAX_VALUE/1_000_000_000) && candidate.nanoTime>=0 && candidate.nanoTime<=time*1_000_000+1_000_000){"invalid capture timestamp"}
            val old=observed
            if(old!=null) {
                check(candidate.frames>=old.frames && candidate.nanoTime>=old.nanoTime){"capture timestamp regressed"}
                if(old.frames>0 && candidate.frames>old.frames) {
                    val frames=candidate.frames-old.frames
                    val nanos=candidate.nanoTime-old.nanoTime
                    check(nanos>0 && nanos<=Long.MAX_VALUE/MAX_RATE){"incoherent capture time"}
                    check(frames*1_000_000_000>=nanos*MIN_RATE-2_000_000_000 &&
                        frames*1_000_000_000<=nanos*MAX_RATE+2_000_000_000){"capture rate outside bound"}
                }
                // A stationary frame must not be made fresh by changing its timestamp.
                check(candidate.frames!=old.frames || candidate.nanoTime==old.nanoTime){"capture timestamp relabeled"}
            }
            observed=candidate
        }
        val value=observed
        if(value==null)check(time-monoOrigin<startupMs){"capture timestamp unavailable"}
        else check(time*1_000_000-value.nanoTime<=maxAgeNs){"capture timestamp stale"}
        return value to time
    }
    fun remainingMs():Long {
        val (value,time)=refresh()
        if(value==null)return startupMs-(time-monoOrigin)
        val lag=maxOf(0,time*1_000_000-value.nanoTime)
        val produced=value.frames+(lag*MAX_RATE+999_999_999)/1_000_000_000
        val unread=maxOf(0,produced-readSamples)
        val left=capacity-reserve-unread
        check(left>0){"cumulative native continuity exhausted"}
        val room=left*1000/MAX_RATE
        check(room>0){"cumulative native room exhausted"}
        return room
    }
    fun check(){remainingMs();check(ready){"capture timestamp not ready"}}
    fun read(count:Int):Long {
        require(count>=0);check()
        val value=checkNotNull(observed)
        val lag=maxOf(0,checkedAt*1_000_000-value.nanoTime)
        val upper=value.frames+(lag*MAX_RATE+999_999_999)/1_000_000_000
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
        // Earliest estimate within the explicit short-window rate bound, and 1ms bridge rounding.
        val nativeNs=value.nanoTime+Math.floorDiv(delta*1_000_000_000,rate)
        return bootOrigin+Math.floorDiv(nativeNs-monoOrigin*1_000_000,1_000_000)-1
    }
}
