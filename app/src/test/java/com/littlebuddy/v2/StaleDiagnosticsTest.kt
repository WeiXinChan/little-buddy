package com.littlebuddy.v2

import com.littlebuddy.v2.parent.PinDiagnostic
import org.junit.Assert.*
import org.junit.After
import org.junit.Test

class StaleDiagnosticsTest {
    @After fun reset(){PinDiagnostic.installRuntime(null);CaptureClockDiagnostic.install(null)}
    private class Rig(val endNs:Long=1_040_185_149) {
        var now=1000L;var stamp:CaptureStamp?=CaptureStamp(0,1_000_000_000);var delay=0L
        val ledger=NativeReadLedger(3200,{now},{now}){now+=delay;delay=0;stamp}
        fun ready(){
            ledger.beginStartup()
            now=1021;stamp=CaptureStamp(320,1_020_200_000);ledger.stageRead(320)
            now=1041;stamp=CaptureStamp(640,endNs);ledger.stageRead(320);ledger.finishStartup()
            now=1046;ledger.check()
        }
    }
    @Test fun realReportedApiGapAndAgeRemainTypedStale(){
        val r=Rig();r.ready();r.now=1081;r.delay=113;r.stamp=CaptureStamp(960,1_059_957_688)
        val e=runCatching{r.ledger.check()}.exceptionOrNull() as CaptureClockFailure
        assertEquals(CaptureClockReason.TIMESTAMP_STALE,e.reason)
        assertEquals(134_042_312L,e.evidence.ageNs);assertEquals(137_042_312L,e.evidence.conservativeAgeNs)
        assertEquals(35L,e.evidence.checkGapMs);assertEquals(113L,e.evidence.apiMs)
        assertEquals(1081L,e.evidence.apiBeforeMs);assertEquals(1194L,e.evidence.apiAfterMs)
        assertEquals(19_772_539L,e.evidence.deltaNs);assertEquals(100_000_000L,e.evidence.maxAgeNs)
        assertEquals(2_000_000L,e.evidence.phaseNs);assertTrue(e.evidence.stampReturned);assertFalse(e.evidence.starting)
        assertEquals(640L,r.ledger.readSamples)
    }
    @Test fun identicalPairStalesAtExactExistingBoundary(){
        val r=Rig();r.ready();r.now=1137;r.ledger.check() // raw age 96.814851ms +3ms <100
        r.now=1138
        val e=runCatching{r.ledger.check()}.exceptionOrNull() as CaptureClockFailure
        assertEquals(CaptureClockReason.TIMESTAMP_STALE,e.reason)
    }
    @Test fun exact100msConservativeAgePassesButOneNsOverRefuses(){
        val pass=Rig(1_040_000_000);pass.ready();pass.now=1137;pass.ledger.check()
        val reject=Rig(1_039_999_999);reject.ready();reject.now=1137
        val e=runCatching{reject.ledger.check()}.exceptionOrNull() as CaptureClockFailure
        assertEquals(CaptureClockReason.TIMESTAMP_STALE,e.reason);assertEquals(100_000_001L,e.evidence.conservativeAgeNs)
    }
    @Test fun unavailableApiUsesOldObservationWithoutFreshnessRenewal(){
        val r=Rig();r.ready();r.now=1081;r.delay=113;r.stamp=null
        val e=runCatching{r.ledger.check()}.exceptionOrNull() as CaptureClockFailure
        assertEquals(CaptureClockReason.TIMESTAMP_STALE,e.reason);assertFalse(e.evidence.stampReturned)
        assertEquals(1_040_185_149L,e.evidence.stampNs);assertEquals(640L,r.ledger.readSamples)
    }
    @Test fun currentFailureStillApplies(){assertTrue(CaptureFailureGate.current(2,7,2,7,true))}
    @Test fun queuedSameTransportOldRecorderCannotHoldReplacement(){
        val ownerToUi=java.util.ArrayDeque<()->Unit>();var recorder=7L;var hold=0;var oldHold=0
        val expectedTransport=2L;var currentTransport=2L
        ownerToUi.add{
            if(expectedTransport==currentTransport)oldHold++ // exact pre-fix UI predicate
            if(CaptureFailureGate.current(expectedTransport,7,currentTransport,recorder,true))hold++
        }
        recorder=8;ownerToUi.removeFirst()();assertEquals(0,hold);assertEquals(1,oldHold)
    }
    @Test fun oldTransportAndNewActivityOrFocusCannotApply(){
        assertFalse(CaptureFailureGate.current(2,7,3,8,true));assertFalse(CaptureFailureGate.current(2,7,2,7,false))
    }
    @Test fun cancellationContextDoesNotEraseTypedClockFailure(){
        val observed=mutableListOf<CaptureClockFailure>();CaptureClockDiagnostic.install{observed.add(it)}
        val error=CaptureClockFailure(CaptureClockReason.TIMESTAMP_STALE,CaptureClockEvidence(ageNs=134_042_312),
            context=CaptureClockContext(3,2,7,CaptureReadStep.POST_KWS,true,false,true,false,CaptureTimestampResult.SUCCESS))
        CaptureClockDiagnostic.emit(error)
        assertEquals(CaptureClockReason.TIMESTAMP_STALE,observed.single().reason)
        assertTrue(observed.single().context!!.cancelled);assertEquals(7L,observed.single().context!!.capture)
    }
    @Test fun fixedSourceEnumSeparatesPreviouslyCollapsedFailures(){
        val mapping=mapOf("protocol" to PinDiagnostic.FailSource.RECEIVE_PROTOCOL,"playback" to PinDiagnostic.FailSource.PLAYBACK_PUMP,
            "lifecycle" to PinDiagnostic.FailSource.LIFECYCLE,"route" to PinDiagnostic.FailSource.ROUTE,
            "backpressure" to PinDiagnostic.FailSource.BACKPRESSURE,"management" to PinDiagnostic.FailSource.MANAGEMENT,
            "expired" to PinDiagnostic.FailSource.EXPIRED,"release" to PinDiagnostic.FailSource.RELEASE,
            "network" to PinDiagnostic.FailSource.NETWORK,"closed" to PinDiagnostic.FailSource.CLOSED,"incompatible" to PinDiagnostic.FailSource.INCOMPATIBLE)
        mapping.forEach{(code,expected)->assertEquals(expected,PinDiagnostic.failSource(code))}
        assertEquals(PinDiagnostic.FailSource.OTHER,PinDiagnostic.failSource("arbitrary-body-not-logged"))
        assertEquals(PinDiagnostic.WireKind.OTHER,PinDiagnostic.wireKind("arbitrary-body-not-logged"))
    }
    @Test fun immutableScopeIsNotReplacedByLaterActivitySequence(){
        val seen=mutableListOf<PinDiagnostic.RuntimeEvent>();PinDiagnostic.installRuntime{seen.add(it)}
        val a=PinDiagnostic.nextActivity();val old=PinDiagnostic.Scope(a,2,7);PinDiagnostic.nextActivity()
        PinDiagnostic.runtime(PinDiagnostic.RuntimeEvent(PinDiagnostic.RuntimeStage.CAPTURE_FAILURE,old,cancelled=true))
        assertEquals(old,seen.single().scope)
    }
    @Test fun diagnosticSinkThrowCannotChangeCurrentDecision(){
        PinDiagnostic.installRuntime{error("synthetic diagnostic failure")}
        PinDiagnostic.runtime(PinDiagnostic.RuntimeEvent(PinDiagnostic.RuntimeStage.CLIENT_FAIL,PinDiagnostic.Scope(1,2,0)))
        assertTrue(CaptureFailureGate.current(2,7,2,7,true))
    }
}
