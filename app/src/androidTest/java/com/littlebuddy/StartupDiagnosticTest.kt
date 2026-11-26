package com.littlebuddy
import org.junit.Assert.*
import org.junit.Test
import com.littlebuddy.v2.NativeReadLedger
import com.littlebuddy.v2.CaptureStamp

class StartupDiagnosticTest {
    private class Port(val publication:String):StartupPort {
        var time=0L;var reads=0;var consumed=0L;var cancelled=false;var buffer:ShortArray?=null;var throwAfterWrite=false
        override fun nowMs()=time
        override fun allowed()=!cancelled
        override fun read(samples:ShortArray,count:Int):Int {
            reads++;buffer=samples;samples.fill(7)
            if(throwAfterWrite)throw IllegalStateException("synthetic")
            val n=minOf(count.toLong(),maxOf(0,time*16-consumed)).toInt();consumed+=n;return n
        }
        override fun timestamp():StartupApiSample {
            val available=when(publication){"read"->reads>0 && time>=20;"delay"->time>=250;"bad"->true;else->false}
            return if(!available)StartupApiSample(-3) else if(publication=="bad")StartupApiSample(0,-1,-1)
                else StartupApiSample(0,time*16,time*1_000_000)
        }
        override fun pause(ms:Long){time+=ms}
    }
    @Test fun originalReadyBeforeReadGateDeterministicallyDeadlocksWhenPublicationNeedsRead(){
        val port=Port("read")
        val ledger=NativeReadLedger(3200,{port.time},{port.time}){
            val s=port.timestamp();if(s.code==0)CaptureStamp(s.frames,s.nanoTime) else null
        }
        val failure=runCatching{while(!ledger.ready){ledger.remainingMs();port.pause(5)}}.exceptionOrNull()
        assertEquals("capture timestamp unavailable",failure?.message);assertEquals(0,port.reads);assertEquals(180L,port.time)
    }
    @Test fun twoBoundedModesDistinguishReadAssociationWithoutAuthorizingProduction(){
        val a=StartupObservation(StartupMode.TIMESTAMP_ONLY);val pa=Port("read");StartupDiagnostic.run(pa,a)
        val b=StartupObservation(StartupMode.READ_THEN_TIMESTAMP);val pb=Port("read");StartupDiagnostic.run(pb,b)
        assertEquals(0,a.readCalls);assertEquals(-1L,a.firstSuccessMs);assertTrue(b.firstSuccessMs>=20)
        assertEquals("READ_PATH_OR_ORDER_WARMUP_ASSOCIATION",StartupDiagnostic.interpretation(a,b))
        assertTrue(a.elapsedMs<=1000 && b.elapsedMs<=1000);assertTrue(b.readSamples<=19200)
        assertTrue(pb.buffer!!.all{it==0.toShort()})
    }
    @Test fun delayedPublicationAndUnavailableRemainDifferentHypotheses(){
        val delayed=StartupMode.entries.map{mode->StartupObservation(mode).also{StartupDiagnostic.run(Port("delay"),it)}}
        assertTrue(delayed.all{it.firstSuccessMs==250L});assertEquals("BOTH_AVAILABLE_IN_WINDOW",StartupDiagnostic.interpretation(delayed[0],delayed[1]))
        val none=StartupMode.entries.map{mode->StartupObservation(mode).also{StartupDiagnostic.run(Port("none"),it)}}
        assertEquals("UNAVAILABLE_IN_TWO_WINDOWS_NOT_PERMANENT_UNSUPPORTED",StartupDiagnostic.interpretation(none[0],none[1]))
    }
    @Test fun cancellationAndNativeThrowWipeReadBuffer(){
        val p=Port("read");p.throwAfterWrite=true
        assertNotNull(runCatching{StartupDiagnostic.run(p,StartupObservation(StartupMode.READ_THEN_TIMESTAMP))}.exceptionOrNull())
        assertTrue(p.buffer!!.all{it==0.toShort()})
        val cancelled=Port("none");cancelled.cancelled=true
        assertEquals("DIAG_CANCELLED",runCatching{StartupDiagnostic.run(cancelled,StartupObservation(StartupMode.READ_THEN_TIMESTAMP))}.exceptionOrNull()?.message)
        assertEquals(0,cancelled.reads)
    }
    @Test fun frozenClockHasFiniteStepAndSampleLimitsAndInvalidPairCannotLookHealthy(){
        val port=object:StartupPort{override fun nowMs()=0L;override fun allowed()=true
            override fun read(samples:ShortArray,count:Int):Int {samples.fill(7);return count}
            override fun timestamp()=StartupApiSample(-3);override fun pause(ms:Long){} }
        val a=StartupObservation(StartupMode.TIMESTAMP_ONLY);StartupDiagnostic.run(port,a);assertEquals(128,a.apiCalls)
        val b=StartupObservation(StartupMode.READ_THEN_TIMESTAMP);StartupDiagnostic.run(port,b);assertEquals(19200L,b.readSamples)
        val bad=StartupObservation(StartupMode.TIMESTAMP_ONLY);StartupDiagnostic.run(Port("bad"),bad)
        assertEquals("API_PAIR_ANOMALY",StartupDiagnostic.interpretation(bad,b))
    }
}
