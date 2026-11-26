package com.littlebuddy

import org.junit.Assert.*
import org.junit.AssumptionViolatedException
import org.junit.Test
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** Actual kernel/decision paths; controlled engines test ordering, not ONNX performance. */
class WakeHitOrderingTest {
    private val repo=File(System.getProperty("wake.repo"))
    private fun target(path:String)=File(repo,"app/src/main/assets/$path").inputStream()
    private fun fixture(path:String)=File(repo,"app/src/androidTest/assets/$path").inputStream()
    private val released=ProbeReleaseProof(true,true,true,true,true,true)
    private fun verdict(raw:Throwable,cancelled:Boolean):ProbeDecision {
        val error=classifyWakeFailure(raw){cancelled}
        return decideProbeResult((error as? WakeProbeDependency)?.code ?: "",(error as? WakeProbeViolation)?.code ?: "",
            probeFailureClass(error),"","",released)
    }
    private fun verifyInvalid(k:WakeFixtureKernel,error:Throwable,tail:Long,expected:String){
        assertEquals(tail,k.currentTail);assertEquals(1,k.currentHits);assertEquals(320,k.currentOffered)
        assertEquals(k.attempted,k.closed);assertTrue(k.scratchIsClear())
        assertTrue(error is WakeProbeViolation);assertEquals(expected,(error as WakeProbeViolation).code)
        val decision=verdict(error,true);assertEquals("FAIL",decision.outcome);assertTrue(decision.junitFailure)
        val thrown=runCatching{decision.enforce()}.exceptionOrNull()
        assertTrue(thrown is AssertionError);assertFalse(thrown is AssumptionViolatedException)
    }
    @Test fun invalidObservedHitsBeatSynchronousCancelForAllInputKinds(){
        val cases=listOf(0 to 1L,1 to 1L)+listOf(2,3).flatMap{index->listOf(-1L,0L,321L).map{index to it}}
        for((at,tail) in cases){
            var cancelled=false;var index=0
            val k=WakeFixtureKernel(WakeProbeBudget({0},{0}),{!cancelled},::target,::fixture,
                {val i=index++;object:WakeProbeEngine {
                    override fun accept(samples:ShortArray,count:Int):Long?=
                        if(i==at){cancelled=true;tail}else if(i>=2)160L else null
                    override fun close(){}
                }})
            val error=runCatching{k.run()}.exceptionOrNull()!!
            verifyInvalid(k,error,tail,if(at<2)"WAKE_UNEXPECTED_HIT" else "WAKE_TAIL_OUTSIDE_INPUT")
            assertEquals(listOf("silence","command_alone","wake","gap_120")[at],k.currentCase)
            assertEquals(at,k.results.size) // Failed observation is not hidden behind completed cases.
        }
    }
    @Test fun invalidObservationAlsoSurvivesLaterCancellationInClose(){
        var cancelled=false
        val k=WakeFixtureKernel(WakeProbeBudget({0},{0}),{!cancelled},::target,::fixture,
            {object:WakeProbeEngine {
                override fun accept(samples:ShortArray,count:Int)=1L
                override fun close(){cancelled=true}
            }})
        val error=runCatching{k.run()}.exceptionOrNull()!!
        assertTrue(cancelled);verifyInvalid(k,error,1L,"WAKE_UNEXPECTED_HIT")
    }
    @Test fun cancellationBeforeAcceptDoesNotInventAnObservation(){
        var cancelled=false;var calls=0
        val k=WakeFixtureKernel(WakeProbeBudget({0},{0}),{!cancelled},::target,::fixture,
            {cancelled=true;object:WakeProbeEngine {
                override fun accept(samples:ShortArray,count:Int):Long?{calls++;return 1L}
                override fun close(){}
            }})
        val error=runCatching{k.run()}.exceptionOrNull()!!
        assertEquals(0,calls);assertEquals(0,k.currentOffered);assertNull(k.currentTail)
        assertEquals(1,k.closed);assertTrue(k.scratchIsClear())
        val decision=verdict(error,true);assertEquals("NOT_RUN_DEPENDENCY",decision.outcome)
        assertTrue(runCatching{decision.enforce()}.exceptionOrNull() is AssumptionViolatedException)
    }
    @Test fun validHitOrNoHitWithCancelStillExitsDependencyAndNeverPasses(){
        val cases=listOf(0 to null,1 to null,2 to null,3 to null,2 to 1L,2 to 320L,3 to 1L,3 to 320L)
        for((at,tail) in cases){
            var cancelled=false;var index=0
            val k=WakeFixtureKernel(WakeProbeBudget({0},{0}),{!cancelled},::target,::fixture,
                {val i=index++;object:WakeProbeEngine {
                    override fun accept(samples:ShortArray,count:Int):Long?=
                        if(i==at){cancelled=true;tail}else if(i>=2)160L else null
                    override fun close(){}
                }})
            val error=runCatching{k.run()}.exceptionOrNull()!!
            assertEquals(tail,k.currentTail);assertEquals(320,k.currentOffered)
            assertEquals(k.attempted,k.closed);assertTrue(k.scratchIsClear())
            val d=verdict(error,true);assertEquals("NOT_RUN_DEPENDENCY",d.outcome);assertFalse(d.junitFailure)
            assertTrue(runCatching{d.enforce()}.exceptionOrNull() is AssumptionViolatedException)
        }
    }
    @Test fun callerCancelWhileAcceptBlockedRetainsInvalidResultWhenItReturns(){
        val entered=CountDownLatch(1);val release=CountDownLatch(1);val cancelled=AtomicBoolean(false)
        var failure:Throwable?=null
        val k=WakeFixtureKernel(WakeProbeBudget({0},{0}),{!cancelled.get()},::target,::fixture,
            {object:WakeProbeEngine {
                override fun accept(samples:ShortArray,count:Int):Long?{
                    entered.countDown();check(release.await(3,TimeUnit.SECONDS));return 1L}
                override fun close(){}
            }})
        val thread=Thread{try{k.run()}catch(error:Throwable){failure=error}}
        thread.start()
        try {assertTrue(entered.await(3,TimeUnit.SECONDS));cancelled.set(true);k.clear()}
        finally{release.countDown();thread.join(3000)}
        assertFalse(thread.isAlive);verifyInvalid(k,checkNotNull(failure),1L,"WAKE_UNEXPECTED_HIT")
    }
}
