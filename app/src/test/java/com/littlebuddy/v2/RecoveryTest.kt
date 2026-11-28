package com.littlebuddy.v2

import org.junit.Assert.*
import org.junit.Test

class RecoveryTest {
    @Test fun onlyOneWakeAndOneCuePerEpisodeAcrossForegroundGenerations(){
        val r=RecoveryEpisode();assertNull(r.grant(true,true));assertTrue(r.begin())
        assertNull(r.grant(false,true));assertNull(r.grant(true,false))
        val a=r.grant(true,true)!!;assertTrue(r.cue(a));assertFalse(r.cue(a))
        r.pause();assertFalse(r.current(a));val b=r.grant(true,true)!!;assertFalse(r.cue(b))
        assertTrue(r.consumeWake(b));assertFalse(r.consumeWake(b));assertNull(r.grant(true,true))
        val gate=RuntimeRetryGate();gate.technicalFailure()
        gate.recoverySucceeded(r.succeeded(b)!!);assertTrue(gate.automaticAllowed);assertFalse(r.hasEpisode());assertTrue(r.current(b));assertFalse(r.consumeWake(b))
        r.pause();assertFalse(r.current(b));assertNull(r.grant(true,true))
    }
    @Test fun blockedFailureCannotBorrowOldGrant(){
        val r=RecoveryEpisode();r.begin();val a=r.grant(true,true)!!;r.block()
        assertFalse(r.consumeWake(a));assertNull(r.succeeded(a));assertNull(r.grant(true,true))
    }
    @Test fun physicalCaptureBindingDoesNotPretendNewRecorderOrAcceptRetiredTicket(){
        val r=RecoveryEpisode();r.begin();val a=r.grant(true,true)!!;r.consumeWake(a)
        val scope=com.littlebuddy.v2.parent.PinDiagnostic.Scope(1,2,7)
        val wake=WakeBoundary(100000,640,960,40)
        assertNull(r.binding(a,scope,2,wake))
        val event=r.binding(a,scope,3,wake)!!
        assertEquals(scope,event.scope);assertEquals(3L,event.currentTransport);assertEquals(7L,event.currentCapture)
        assertEquals(100000L,event.wakeBootMs);assertEquals(640L,event.wakeFrame)
        assertNull(r.binding(a,scope,3,wake));r.pause();assertNull(r.binding(a,scope,4,wake))
    }
    private class Native:TrackPort {
        var releases=0;var stops=0;var writes=0;var failStop=false;var failRelease=false
        override val head=0L
        override fun write(pcm:ShortArray,offset:Int):Int{writes++;return pcm.size-offset}
        override fun play(){}
        override fun pause(){}
        override fun mute(){}
        override fun flush(){}
        override fun stop(){stops++;if(failStop)error("synthetic")}
        override fun release(){releases++;if(failRelease)error("synthetic")}
    }
    @Test fun oldLeaseAndOldRouteCannotAffectNewTrack(){
        val slot=OutputSlot();var route1:(()->Unit)?=null;var signals=0
        val a=Native();val lease=slot.acquire(OutputSlot.Purpose.NORMAL,{cb->route1=cb;a},{signals++})
        assertThrows(IllegalStateException::class.java){slot.acquire(OutputSlot.Purpose.SERVICE_CUE,{Native()},{})}
        lease.mute();lease.pause();lease.flush();lease.stop();lease.release();assertTrue(slot.idle)
        val b=Native();val next=slot.acquire(OutputSlot.Purpose.SERVICE_CUE,{b},{signals++})
        lease.stop();lease.release();route1!!();assertEquals(0,signals);assertEquals(0,b.releases)
        assertThrows(IllegalStateException::class.java){lease.write(shortArrayOf(1),0)}
        next.stop();next.release();assertEquals(1,b.releases);assertTrue(slot.idle)
    }
    @Test fun stopFailureEvenWithReleasePoisonsSlot(){
        val slot=OutputSlot();val native=Native().also{it.failStop=true}
        val port=slot.acquire(OutputSlot.Purpose.NORMAL,{native},{})
        assertThrows(IllegalStateException::class.java){port.stop()};port.release()
        assertTrue(slot.quarantined);assertFalse(slot.idle);assertEquals(1,native.releases)
    }
    @Test fun factoryFailureWithoutNativeProofPoisonsSlotAndPreventsSecondConstruction(){
        val slot=OutputSlot();var constructions=0
        assertThrows(IllegalArgumentException::class.java){slot.acquire(OutputSlot.Purpose.NORMAL,{constructions++;throw IllegalArgumentException("synthetic")},{})}
        assertTrue(slot.quarantined);assertFalse(slot.idle)
        assertThrows(IllegalStateException::class.java){slot.acquire(OutputSlot.Purpose.SERVICE_CUE,{constructions++;Native()},{})}
        assertEquals(1,constructions)
    }
    @Test fun failedConstructorCleanupCannotLendAuthorityToAnotherNative(){
        val slot=OutputSlot();val native=Native().also{it.failRelease=true};var constructions=0
        assertThrows(IllegalStateException::class.java){slot.acquire(OutputSlot.Purpose.NORMAL,{
            constructions++;try{error("synthetic constructor")}finally{native.release()}
        },{})}
        assertEquals(1,native.releases);assertTrue(slot.quarantined);assertFalse(slot.idle)
        assertThrows(IllegalStateException::class.java){slot.acquire(OutputSlot.Purpose.NORMAL,{constructions++;Native()},{})}
        assertEquals(1,constructions)
    }
    @Test fun releaseFailureRetainsQuarantine(){
        val slot=OutputSlot();val n=Native().also{it.failRelease=true};val p=slot.acquire(OutputSlot.Purpose.NORMAL,{n},{})
        p.stop();assertThrows(IllegalStateException::class.java){p.release()};assertTrue(slot.quarantined)
        assertThrows(IllegalStateException::class.java){slot.acquire(OutputSlot.Purpose.SERVICE_CUE,{Native()},{})}
    }
}
