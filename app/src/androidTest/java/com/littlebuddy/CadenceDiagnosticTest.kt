package com.littlebuddy

import com.littlebuddy.v2.CaptureStamp
import com.littlebuddy.v2.NativeReadLedger
import org.junit.Assert.*
import org.junit.Test

class CadenceDiagnosticTest {
    private class Port(val jitter:Boolean=false,val rate:Long=16000):CadencePort {
        val start=1_000_000_000L;var now=start;var consumed=0L;var cancelled=false
        var apiCost=0L;var readCost=0L;var throwRead=false;var freeze=false;var timestampCalls=0
        var kept:ShortArray?=null
        override fun monoNs()=now
        override fun bootNs()=now+5_000_000_000
        override fun allowed()=!cancelled
        override fun read(samples:ShortArray,count:Int):Int {
            now+=readCost;kept=samples;samples.fill(7)
            if(throwRead)throw IllegalStateException("synthetic")
            val available=(now-start)*16000/1_000_000_000/320*320-consumed
            val n=minOf(count.toLong(),available).toInt();consumed+=n;return n
        }
        override fun timestamp():StartupApiSample {
            now+=apiCost;timestampCalls++
            val elapsed=now-start-40_000_000
            if(elapsed<20_000_000)return StartupApiSample(-3)
            val frames=(elapsed*rate/1_000_000_000/320)*320
            val phase=if(jitter && frames/320%2==1L)178846L else 0L
            return StartupApiSample(0,frames,start+frames*1_000_000_000/rate+phase)
        }
        override fun pause(){if(!freeze)now+=5_000_000}
    }
    @Test fun rawRc7PairFailsUnchangedProductionLedgerAndExactOldOracle(){
        val last=24523524159076L;val delta=20178846L;val previous=last-delta
        var time=previous-50*20_000_000L;var frames=640L
        val ledger=NativeReadLedger(3200,{time/1_000_000},{time/1_000_000}){CaptureStamp(frames,time)}
        repeat(51){i->frames=(i+2)*320L;time=previous-(50-i)*20_000_000L;ledger.read(320)}
        assertEquals(16320L,ledger.readSamples);frames=16960;time=last
        val error=runCatching{ledger.check()}.exceptionOrNull()
        assertEquals("capture rate outside bound",error?.message)
        assertTrue(CadenceDiagnostic.oldRateReject(320,delta))
        println("RC7_ORIGINAL_PAIR df=320 dn=$delta ledger=${error?.message} lower_deficit_frames=0.538674464")
    }
    @Test fun finiteAlternatingJitterAndSustainedDriftProduceDifferentLongWindowEvidence(){
        val jitter=CadenceObservation();val jp=Port(jitter=true);CadenceDiagnostic.run(jp,jitter)
        assertEquals("WINDOW_LIMIT",jitter.terminal);assertTrue(jitter.rateRejections>0)
        val jw=jitter.rows.filter{it.windowNs>0};assertTrue(jw.isNotEmpty())
        assertTrue(jw.all{!CadenceDiagnostic.oldRateReject(it.windowFrames,it.windowNs)})
        for(rate in listOf(15800L,16200L)){
            val drift=CadenceObservation();CadenceDiagnostic.run(Port(rate=rate),drift)
            assertTrue(drift.rows.any{it.windowNs>0 && CadenceDiagnostic.oldRateReject(it.windowFrames,it.windowNs)})
        }
        assertTrue(jp.kept!!.all{it==0.toShort()})
        println("CONTROLLED_JITTER short_rejects=${jitter.rateRejections} long_windows=${jw.size} long_rejects=0; sustained +/-12500ppm long_rejects>0 (not hardware evidence)")
    }
    @Test fun readCrossingDeadlineKeepsCountWipesAndStartsNoApi(){
        val p=Port();p.readCost=CadenceDiagnostic.WINDOW_NS+1
        val r=CadenceObservation();runCatching{CadenceDiagnostic.run(p,r)}
        assertEquals(320L,r.samples);assertEquals(0,p.timestampCalls);assertTrue(p.kept!!.all{it==0.toShort()})
    }
    @Test fun lateApiSuccessIsKeptAsLateAndNeverInWindowHealth(){
        val p=Port();p.apiCost=CadenceDiagnostic.WINDOW_NS+1
        val r=CadenceObservation();runCatching{CadenceDiagnostic.run(p,r)}
        assertEquals(1,r.apiCalls);assertEquals(1,r.rows.size);assertTrue(r.rows.single().late)
        assertTrue(r.firstSuccessElapsedNs>=CadenceDiagnostic.WINDOW_NS);assertTrue(r.lateCalls>0)
    }
    @Test fun cancellationNativeThrowAndFrozenClockAreFiniteAndZeroScratch(){
        val cancelled=Port();cancelled.cancelled=true
        assertEquals("CADENCE_CANCELLED",runCatching{CadenceDiagnostic.run(cancelled,CadenceObservation())}.exceptionOrNull()?.message)
        val broken=Port();broken.throwRead=true
        assertNotNull(runCatching{CadenceDiagnostic.run(broken,CadenceObservation())}.exceptionOrNull())
        assertTrue(broken.kept!!.all{it==0.toShort()})
        val frozen=Port();frozen.freeze=true;val r=CadenceObservation();CadenceDiagnostic.run(frozen,r)
        assertEquals(CadenceDiagnostic.MAX_API,r.apiCalls);assertEquals("API_LIMIT",r.terminal)
    }
    @Test fun originalLimitsAndMetadataNeverSilentlyGrow(){
        val p=Port();val r=CadenceObservation();CadenceDiagnostic.run(p,r)
        assertTrue(r.samples<=64000);assertTrue(r.apiCalls<=2048);assertTrue(r.rows.size<=256)
        assertTrue(r.rows.all{it.apiAfterNs>=it.apiBeforeNs && it.bootAfterNs>=it.bootBeforeNs})
        assertTrue(r.rows.zipWithNext().all{(a,b)->a.frames!=b.frames || a.stampNs!=b.stampNs})
        assertTrue(r.rows.all{it.readSamples<=r.samples})
    }
    // The read-return checkpoint sees time inside the window; only the next clock sample jumps.
    private class SchedulingPort(val atRead:Int,val apiBefore:Long):CadencePort {
        var now=0L;var reads=0;var afterReadClocks=0;var calls=0;var cancelAfterApi=false
        var scratch:ShortArray?=null
        override fun monoNs():Long {
            if(reads>0 && ++afterReadClocks==2 && reads==atRead)now=apiBefore
            return now
        }
        override fun bootNs()=now
        override fun allowed()=!cancelAfterApi
        override fun read(samples:ShortArray,count:Int):Int {
            now+=20_000_000;reads++;afterReadClocks=0;scratch=samples;samples.fill(3);return count
        }
        override fun timestamp():StartupApiSample {
            calls++
            if(reads==atRead){now++;cancelAfterApi=apiBefore<CadenceDiagnostic.WINDOW_NS-1}
            return StartupApiSample(0,reads*320L,now)
        }
        override fun pause(){}
    }
    @Test fun finalAdmissionJustBeforeDeadlinePreservesLateReturnButAtDeadlineStartsNoApi(){
        val before=SchedulingPort(174,CadenceDiagnostic.WINDOW_NS-1);val br=CadenceObservation()
        CadenceDiagnostic.run(before,br)
        assertEquals(174,before.calls);assertEquals(1,br.lateCalls);assertTrue(br.rows.last().late)
        assertEquals(CadenceDiagnostic.WINDOW_NS,br.rows.last().apiAfterNs)
        val equal=SchedulingPort(174,CadenceDiagnostic.WINDOW_NS);val er=CadenceObservation()
        CadenceDiagnostic.run(equal,er)
        assertEquals(173,equal.calls);assertEquals(173,er.apiCalls);assertEquals(0,er.lateCalls)
        assertEquals("WINDOW_LIMIT",er.terminal);assertEquals(174*320L,er.samples)
        assertTrue(before.scratch!!.all{it==0.toShort()});assertTrue(equal.scratch!!.all{it==0.toShort()})
        println("PRE_API_BOUNDARY before_calls=${before.calls} late=${br.lateCalls}; equal_calls=${equal.calls} late=${er.lateCalls}")
    }
    @Test fun finalAdmissionChargesSchedulingGapAgainstRemainingNativeRoom(){
        val within=SchedulingPort(1,198_000_000);val wr=CadenceObservation()
        assertEquals("CADENCE_CANCELLED",runCatching{CadenceDiagnostic.run(within,wr)}.exceptionOrNull()?.message)
        assertEquals(1,within.calls)
        val exhausted=SchedulingPort(1,199_000_000);val er=CadenceObservation()
        assertEquals("CADENCE_READ_ROOM_EXHAUSTED",runCatching{CadenceDiagnostic.run(exhausted,er)}.exceptionOrNull()?.message)
        assertEquals(0,exhausted.calls);assertEquals(0,er.apiCalls);assertEquals(320L,er.samples)
        assertTrue(within.scratch!!.all{it==0.toShort()});assertTrue(exhausted.scratch!!.all{it==0.toShort()})
        println("PRE_API_ROOM within_calls=${within.calls} exhausted_calls=${exhausted.calls}; samples=${er.samples}")
    }

}
