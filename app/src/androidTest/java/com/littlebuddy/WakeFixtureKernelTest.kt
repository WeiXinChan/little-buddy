package com.littlebuddy

import org.junit.Assert.*
import com.littlebuddy.v2.ProcessRecorders
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** Guard/cleanup orchestration ONLY: fake engine hits are never JNI/model evidence. */
class WakeFixtureKernelTest {
    private val repo=File(System.getProperty("wake.repo"))
    private fun target(path:String)=File(repo,"app/src/main/assets/$path").inputStream()
    private fun fixture(path:String)=File(repo,"app/src/androidTest/assets/$path").inputStream()
    private class Fake(val hit:Long?):WakeProbeEngine {
        var closes=0;var last:ShortArray?=null
        override fun accept(samples:ShortArray,count:Int):Long?{last=samples;return hit}
        override fun close(){closes++}
    }
    private fun mustFail(action:()->Unit):WakeProbeViolation {
        val e=runCatching(action).exceptionOrNull();assertTrue(e is WakeProbeViolation);return e as WakeProbeViolation
    }
    @Test fun exactMethodAndAllFlagsRequiredWithoutChangingTimestampSelection(){
        assertTrue(WakeProbeSelection.permits(WakeProbeSelection.METHOD,"true","true","true"))
        for(flags in listOf(listOf(null,"true","true"),listOf("true","false","true"),listOf("true","true",null)))
            assertFalse(WakeProbeSelection.permits(WakeProbeSelection.METHOD,flags[0],flags[1],flags[2]))
        for(m in listOf(null,"com.littlebuddy.NativeWakeModelTest",WakeProbeSelection.METHOD+",other",NativeProbeSelection.SHORT))
            assertFalse(WakeProbeSelection.permits(m,"true","true","true"))
        assertFalse(NativeProbeSelection.permits(WakeProbeSelection.METHOD,"true","true","true","true","true"))
    }
    @Test fun unknownPathDurationAndSecondaryTestSelectorsAreRejected(){
        val valid=setOf("class","nativeWakeModelProbe","businessIdlePreflight","knownWakeFixtures")
        assertTrue(WakeProbeSelection.permitsKeys(valid))
        for(key in listOf("pcm","url","duration","listener","testFile","package","runnerBuilder"))
            assertFalse(key,WakeProbeSelection.permitsKeys(valid+key))
    }
    @Test fun frozenInputsHashAndFourFreshModelsCloseWithZeroScratch(){
        val models=mutableListOf<Fake>();val kernel=WakeFixtureKernel(WakeProbeBudget({0},{0}),{true},::target,::fixture,
            {Fake(if(models.size>=2)160L else null).also{models.add(it)}})
        kernel.run();assertTrue(kernel.hashesVerified);assertEquals(4,models.size);assertEquals(4,kernel.closed)
        assertEquals(listOf(0,0,1,1),kernel.results.map{it.hits});assertEquals(94104L,kernel.totalFed)
        assertTrue(models.all{it.closes==1 && it.last!!.all{s->s==0.toShort()}});assertTrue(kernel.scratchIsClear())
    }
    @Test fun hashMismatchRejectsBeforeAnyNativeConstructor(){
        var constructors=0
        val kernel=WakeFixtureKernel(WakeProbeBudget({0},{0}),{true},
            {path->val data=target(path).use{it.readBytes()};data[0]=(data[0].toInt() xor 1).toByte();ByteArrayInputStream(data)},::fixture,
            {constructors++;Fake(null)})
        assertEquals("WAKE_ASSET_HASH",mustFail{kernel.run()}.code);assertEquals(0,constructors);assertTrue(kernel.scratchIsClear())
    }
    @Test fun positiveMustReallyHitAndRawTailCannotBeClamped(){
        for(tail in listOf<Long?>(null,321L,-1L)){
            var count=0;val models=mutableListOf<Fake>()
            val k=WakeFixtureKernel(WakeProbeBudget({0},{0}),{true},::target,::fixture,
                {Fake(if(count++>=2)tail else null).also{models.add(it)}})
            val e=mustFail{k.run()};assertEquals(if(tail==null)"WAKE_EXPECTED_HIT_MISSING" else "WAKE_TAIL_OUTSIDE_INPUT",e.code)
            assertEquals("wake",k.currentCase);assertEquals(tail,k.currentTail)
            assertTrue(models.all{it.closes==1});assertTrue(k.scratchIsClear())
        }
    }
    @Test fun silenceHitAndCommandAloneHitBothRejectAndClose(){
        for(at in listOf(0,1)){
            var count=0;val models=mutableListOf<Fake>()
            val k=WakeFixtureKernel(WakeProbeBudget({0},{0}),{true},::target,::fixture,
                {Fake(if(count++==at)1L else null).also{models.add(it)}})
            assertEquals("WAKE_UNEXPECTED_HIT",mustFail{k.run()}.code);assertTrue(models.all{it.closes==1})
        }
    }
    @Test fun lateConstructorAndLateAcceptRemainFailureAfterCancellation(){
        for(phase in listOf("constructor","accept")){
            var time=0L;var cancelled=false;val model=object:WakeProbeEngine {
                var closes=0
                override fun accept(samples:ShortArray,count:Int):Long?{time=60000;cancelled=true;return null}
                override fun close(){closes++}
            }
            val k=WakeFixtureKernel(WakeProbeBudget({time},{0}),{!cancelled},::target,::fixture,
                {if(phase=="constructor"){time=60000;cancelled=true};model})
            val e=mustFail{k.run()};assertEquals("WAKE_WALL_BUDGET",e.code);assertEquals(1,model.closes)
            assertSame(e,classifyWakeFailure(e){throw RuntimeException("PRIVATE_SYNTHETIC_MESSAGE")})
        }
    }
    @Test fun cancelClearsScratchBeforeBlockedWorkerReturnsAndThenCloses(){
        val entered=CountDownLatch(1);val release=CountDownLatch(1);val cancelled=AtomicBoolean(false)
        var caught:Throwable?=null;var closes=0;var scratch:ShortArray?=null
        val k=WakeFixtureKernel(WakeProbeBudget({0},{0}),{!cancelled.get()},::target,::fixture,
            {object:WakeProbeEngine {
                override fun accept(samples:ShortArray,count:Int):Long?{
                    scratch=samples;samples[0]=1;entered.countDown();check(release.await(3,TimeUnit.SECONDS));return null}
                override fun close(){closes++}
            }})
        val thread=Thread{try{k.run()}catch(e:Throwable){caught=e}}
        thread.start()
        try {assertTrue(entered.await(3,TimeUnit.SECONDS));cancelled.set(true);k.clear()
            assertTrue(scratch!!.all{it==0.toShort()});assertTrue(thread.isAlive);assertEquals(0,k.closed)
        }finally{release.countDown();thread.join(3000)}
        assertFalse(thread.isAlive);assertTrue(caught is WakeProbeDependency);assertEquals(1,closes);assertTrue(k.scratchIsClear())
    }
    @Test fun thrownConstructorOrCloseNeverClaimsCompleteRelease(){
        for(phase in listOf("constructor","close")){
            val k=WakeFixtureKernel(WakeProbeBudget({0},{0}),{true},::target,::fixture,
                {if(phase=="constructor")throw IllegalStateException("PRIVATE_SYNTHETIC_MESSAGE")
                 object:WakeProbeEngine {override fun accept(samples:ShortArray,count:Int):Long?=1L
                     override fun close(){throw IllegalStateException("PRIVATE_SYNTHETIC_MESSAGE")}}})
            assertNotNull(runCatching{k.run()}.exceptionOrNull());assertEquals(1,k.attempted);assertEquals(0,k.closed)
            val d=decideProbeResult("DEPENDENCY_WAKE_FOREGROUND_LOST","","",k.cleanupClass,"",
                ProbeReleaseProof(true,true,true,true,true,false))
            assertTrue(d.junitFailure);assertEquals("FAIL",d.outcome)
            assertTrue(runCatching{d.enforce()}.exceptionOrNull() is AssertionError)
        }
    }
    @Test fun cancellationBeforeSlowCloseCannotWashOutFinalBudgetViolation(){
        var time=0L;var cancelled=false;var closed=0
        val k=WakeFixtureKernel(WakeProbeBudget({time},{0}),{!cancelled},::target,::fixture,
            {object:WakeProbeEngine {
                override fun accept(samples:ShortArray,count:Int):Long?{cancelled=true;return null}
                override fun close(){closed++;time=60_000}
            }})
        val error=runCatching{k.run()}.exceptionOrNull()
        assertEquals(1,closed);assertTrue("late release must retain budget FAIL, not dependency",error is WakeProbeViolation)
        assertEquals("WAKE_WALL_BUDGET",(error as WakeProbeViolation).code)
    }
    @Test fun actualProcessLeaseRefusesAnotherProbeUntilModelsAndWorkerConfirmed(){
        val hold=checkNotNull(ProcessRecorders.acquire("wake-host-guard"))
        try {
            hold.nativeReleased();hold.workerFinished()
            assertFalse(hold.complete());assertNull(ProcessRecorders.acquire("other-child-or-management"))
            hold.modelsReleased();assertTrue(hold.complete())
        }finally{hold.nativeReleased();hold.modelsReleased();hold.workerFinished()}
        val next=checkNotNull(ProcessRecorders.acquire("next"))
        next.nativeReleased();next.modelsReleased();next.workerFinished();assertEquals("released",ProcessRecorders.diagnostic())
    }
    @Test fun cpuWallSampleAndClockBoundsAreIndependentAndFixed(){
        var wall=0L;var cpu=0L;val b=WakeProbeBudget({wall},{cpu})
        b.check(WakeProbeBudget.SAMPLE_CAP)
        assertEquals("WAKE_SAMPLE_BUDGET",mustFail{b.check(WakeProbeBudget.SAMPLE_CAP+1)}.code)
        cpu=45000;assertEquals("WAKE_CPU_BUDGET",mustFail{b.check(0)}.code)
        wall=60000;assertEquals("WAKE_WALL_BUDGET",mustFail{b.check(0)}.code)
        wall=59999;assertEquals("WAKE_CLOCK_REGRESSED",mustFail{b.check(0)}.code)
    }
}
