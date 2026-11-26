package com.littlebuddy

internal interface CadencePort {
    fun monoNs():Long
    fun bootNs():Long
    fun allowed():Boolean
    fun read(samples:ShortArray,count:Int):Int
    fun timestamp():StartupApiSample
    fun pause()
}
internal data class CadenceOrigin(val mono:Long,val bootLow:Long,val bootHigh:Long)
internal data class CadenceRow(val index:Int,val frames:Long,val stampNs:Long,
    val apiBeforeNs:Long,val apiAfterNs:Long,val bootBeforeNs:Long,val bootAfterNs:Long,
    val readSamples:Long,val adjacentFrames:Long,val adjacentNs:Long,
    val cumulativeFrames:Long,val cumulativeNs:Long,val windowFrames:Long,val windowNs:Long,
    val legacyRateRejected:Boolean,val flags:String,val late:Boolean)
internal class CadenceStopped(val code:String):IllegalStateException(code)
internal class CadenceObservation {
    val rows=mutableListOf<CadenceRow>()
    val codes=sortedMapOf<Int,Int>()
    var readCalls=0;var samples=0L;var emptyReads=0;var apiCalls=0;var successful=0
    var elapsedNs=0L;var firstSuccessElapsedNs=-1L;var maxApiNs=0L;var maxAgeNs=Long.MIN_VALUE
    var maxReadNs=0L;var rateRejections=0;var anomalies=0;var lateCalls=0;var terminal="NOT_STARTED"
}
/** Observation ONLY: no production ledger gate is replaced or declared passed. PCM is never kept. */
internal object CadenceDiagnostic {
    const val WINDOW_NS=3_500_000_000L
    const val MAX_API=2048
    const val MAX_SAMPLES=64000L
    const val MAX_ROWS=256
    const val LONG_WINDOW_NS=500_000_000L
    fun origin(p:CadencePort):CadenceOrigin {
        val low=p.bootNs();val mono=p.monoNs();return CadenceOrigin(mono,low,p.bootNs())
    }
    // Exact existing +/-1000ppm, two-frame pair test, not a new permission or drift estimator.
    fun oldRateReject(df:Long,dn:Long):Boolean = df>0 &&
        (dn<=0 || df>Long.MAX_VALUE/1_000_000_000 || dn>(Long.MAX_VALUE-2_000_000_000)/16016 ||
         df*1_000_000_000<dn*15984-2_000_000_000 || df*1_000_000_000>dn*16016+2_000_000_000)
    fun run(p:CadencePort,r:CadenceObservation,o:CadenceOrigin=origin(p)) {
        val frame=ShortArray(320);var lastMono=o.mono
        fun checkpoint():Long {
            if(!p.allowed())throw CadenceStopped("CADENCE_CANCELLED")
            val bootLow=p.bootNs();val time=p.monoNs();val bootHigh=p.bootNs()
            if(time<lastMono)throw CadenceStopped("CADENCE_CLOCK_REGRESSED")
            if(bootLow-time>o.bootHigh-o.mono+5_000_000 || bootHigh-time<o.bootLow-o.mono-5_000_000)
                throw CadenceStopped("CADENCE_TIMEBASE_CHANGED")
            lastMono=time;r.elapsedNs=time-o.mono;return time
        }
        // Finite observation guard only. Uses pre-start origin, cumulative reads and original buffer.
        // It cannot authorize PCM or prove hardware health; even a completed diagnostic is not PASS.
        fun room(time:Long,readBefore:Long) {
            val elapsed=time-o.mono
            if(elapsed<0 || elapsed>Long.MAX_VALUE/16016-1_000_000)throw CadenceStopped("CADENCE_CLOCK_RANGE")
            val upper=((elapsed+1_000_000)*16016+999_999_999)/1_000_000_000
            if(3200-320-maxOf(0,upper-readBefore)<=0)throw CadenceStopped("CADENCE_READ_ROOM_EXHAUSTED")
        }
        fun limit():Boolean {
            r.terminal=when {
                r.elapsedNs>=WINDOW_NS->"WINDOW_LIMIT"
                r.apiCalls>=MAX_API->"API_LIMIT"
                r.samples>=MAX_SAMPLES->"SAMPLE_LIMIT"
                r.rows.size>=MAX_ROWS->"TRACE_LIMIT"
                else->"RUNNING"
            };return r.terminal!="RUNNING"
        }
        try {
            while(true) {
                val start=checkpoint();if(limit())break;room(start,r.samples)
                val previousRead=r.samples
                try {
                    val count=p.read(frame,minOf(frame.size.toLong(),MAX_SAMPLES-r.samples).toInt())
                    r.readCalls++
                    if(count !in 0..minOf(320L,MAX_SAMPLES-r.samples).toInt())throw CadenceStopped("CADENCE_NATIVE_READ_ERROR")
                    r.samples+=count;if(count==0)r.emptyReads++
                }finally{frame.fill(0)}
                val readEnd=checkpoint();r.maxReadNs=maxOf(r.maxReadNs,readEnd-start)
                room(readEnd,previousRead) // Charge read delay before returned data can renew room.
                if(limit())break
                // Sampling metadata may itself follow a scheduling gap after readEnd.
                // Re-admit the API using fresh clocks/cancellation and charge that gap.
                val bootBefore=p.bootNs();val before=checkpoint()
                if(limit())break
                room(before,r.samples)
                r.apiCalls++
                val value=p.timestamp();val after=p.monoNs();val bootAfter=p.bootNs()
                r.maxApiNs=maxOf(r.maxApiNs,after-before);r.codes[value.code]=(r.codes[value.code] ?: 0)+1
                val late=after-o.mono>=WINDOW_NS;if(late)r.lateCalls++
                if(value.code==0) {
                    r.successful++;if(r.firstSuccessElapsedNs<0)r.firstSuccessElapsedNs=after-o.mono
                    r.maxAgeNs=maxOf(r.maxAgeNs,after-value.nanoTime)
                    val old=r.rows.lastOrNull()
                    if(old==null || old.frames!=value.frames || old.stampNs!=value.nanoTime) {
                        val first=r.rows.firstOrNull{it.frames>0 && it.stampNs>=0}
                        val long=r.rows.lastOrNull{before-it.apiBeforeNs>=LONG_WINDOW_NS}
                        val df=if(old==null)0 else value.frames-old.frames
                        val dn=if(old==null)0 else value.nanoTime-old.stampNs
                        val rejected=old!=null && old.frames>0 && oldRateReject(df,dn)
                        val flags=mutableListOf<String>()
                        if(value.frames<0 || value.frames>Long.MAX_VALUE/1_000_000_000 || value.nanoTime<0 || value.nanoTime>after+1_000_000)flags+="INVALID_PAIR"
                        if(old!=null && (df<0 || dn<0))flags+="REGRESSION"
                        if(old!=null && df==0L && dn!=0L)flags+="STATIONARY_RELABEL"
                        if(after-value.nanoTime>100_000_000)flags+="STALE"
                        if(rejected){flags+="OLD_RATE_REJECT";r.rateRejections++}
                        if(flags.isNotEmpty())r.anomalies++
                        r.rows+=CadenceRow(r.rows.size,value.frames,value.nanoTime,before,after,bootBefore,bootAfter,r.samples,
                            df,dn,if(first==null)0 else value.frames-first.frames,if(first==null)0 else value.nanoTime-first.stampNs,
                            if(long==null)0 else value.frames-long.frames,if(long==null)0 else value.nanoTime-long.stampNs,
                            rejected,flags.joinToString("|"),late)
                    }
                }
                val end=checkpoint();room(end,r.samples);if(limit())break
                if(previousRead==r.samples)p.pause()
            }
        }catch(e:Throwable){r.terminal=if(e is CadenceStopped)e.code else "CADENCE_NATIVE_OR_HARNESS_EXCEPTION";throw e}
        finally{frame.fill(0);r.elapsedNs=maxOf(r.elapsedNs,p.monoNs()-o.mono)}
    }
}
