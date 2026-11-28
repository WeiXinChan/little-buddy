package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
import java.util.ArrayDeque
class HandoffTest {
    private class Rig {
        var now=100000L;var allowed=true;var connections=0;var errors=0;var done=0;var cancels=0
        val jobs=ArrayDeque<Runnable>()
        val q=RecoveryHandoff({now},{jobs.add(it);true},{allowed},{connections++},{cancels++},{errors++},{done++})
        fun wake(){val b=WakeBoundary(100000,320,640,20);q.stageWake(b);q.wake(b)}
        fun drain(){var cap=0;while(jobs.isNotEmpty()){check(cap++<1000);jobs.removeFirst().run()}}
    }
    @Test fun wakeOnlyNeverConnectsOrBuffersWithoutRealWake(){val r=Rig();repeat(100){r.q.check()};assertEquals(0,r.connections);assertEquals(0,r.q.retainedSamples())}
    @Test fun duplicateWakeConnectsOnlyOnce(){val r=Rig();r.wake();r.wake();r.drain();assertEquals(1,r.connections)}
    @Test fun connectDeadlineExactRejectsAndZerosAllPcm(){
        val r=Rig();r.wake();val p=ShortArray(320){7};r.q.stage(listOf(p),true,r.now)
        r.now+=2500;assertThrows(IllegalStateException::class.java){r.q.check()};r.drain()
        assertTrue(p.all{it==0.toShort()});assertEquals(0,r.q.retainedSamples());assertEquals(1,r.errors)
    }
    @Test fun connectImmediatelyBeforeBoundaryKeepsData(){
        val r=Rig();r.wake();val p=ShortArray(320){7};r.q.stage(listOf(p),true,r.now);r.now+=2499;r.q.check();assertEquals(320,r.q.retainedSamples());r.q.cancel();assertTrue(p.all{it==0.toShort()})
    }
    @Test fun exactSampleCapThenNextSampleRejectsAll(){
        val r=Rig();r.wake();val frames=List(150){ShortArray(320){1}};frames.forEach{r.q.stage(listOf(it),true,r.now)};assertEquals(48000,r.q.retainedSamples())
        val extra=shortArrayOf(1);r.q.stage(listOf(extra),true,r.now);r.drain();assertEquals(1,r.errors);assertEquals(0,r.q.retainedSamples());assertTrue(frames.all{f->f.all{it==0.toShort()}});assertEquals(0,extra[0].toInt())
    }
    @Test fun firstSampleAgeNotBatchEndControlsExpiry(){
        val r=Rig();r.wake();val p=ShortArray(320){1};r.q.stage(listOf(p),true,r.now-2981);r.drain();assertEquals(1,r.errors);assertEquals(0,r.q.retainedSamples())
    }
    @Test fun cancellationImmediatelyClearsPendingAndLateWakeDoesNotConnect(){
        val r=Rig();val b=WakeBoundary(100000,320,640,20);r.q.stageWake(b);val p=ShortArray(320){2};r.q.stage(listOf(p),true,r.now);r.q.cancel();r.q.wake(b);r.drain();assertEquals(0,r.connections);assertTrue(p.all{it==0.toShort()})
    }
    @Test fun duplicateAndForeignReadyCannotReimportOrDestroyCurrentFifo(){
        val r=Rig();r.wake();val pcm=ShortArray(320){3};r.q.stage(listOf(pcm),true,r.now)
        val client=VoiceClient();assertTrue(r.q.ready(client));assertTrue(r.q.ready(client))
        assertFalse(r.q.ready(VoiceClient()));r.drain();assertTrue(r.q.ready(client))
        assertEquals(1,client.wakes.size);assertEquals(1,r.done);assertEquals(0,r.errors)
        assertEquals(1,client.received.size);assertTrue(pcm.all{it==0.toShort()})
    }
    @Test fun queuedLiveContinuationStaysBehindPrefixWithoutAliasingScratch(){
        val r=Rig();r.wake();val prefix=ShortArray(320){1};val live=ShortArray(320){2}
        r.q.stage(listOf(prefix),true,r.now);val client=VoiceClient();assertTrue(r.q.ready(client))
        r.q.stage(listOf(live),true,r.now);r.drain()
        assertEquals(listOf(1,2),client.received.map{it[0].toInt()});assertEquals(0,r.q.retainedSamples())
        assertTrue(prefix.all{it==0.toShort()} && live.all{it==0.toShort()});r.q.cancel();assertFalse(r.q.admitted())
    }
    @Test fun permissionLossClearsAndFailsOnce(){val r=Rig();r.wake();r.allowed=false;assertThrows(IllegalStateException::class.java){r.q.check()};r.drain();assertEquals(1,r.errors)}
}
