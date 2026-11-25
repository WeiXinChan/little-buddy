package com.littlebuddy
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Pure tests run on Linux; no AudioRecord/Android stubs or native/environment content. */
class NativeProbeFailureTest {
    private fun requireJunitFail(result:ProbeDecision){
        val thrown=runCatching{result.enforce()}.exceptionOrNull()
        assertNotNull(thrown);assertTrue(thrown is AssertionError)
        assertFalse(thrown is org.junit.AssumptionViolatedException)
    }
    private val released=ProbeReleaseProof(true,true,true,true,true,true)
    @Test fun throwingStopNeverEscapesAndDependencyCannotTurnItIntoSkip(){
        val uncaught=AtomicBoolean(false);val kind=AtomicReference<String?>(null)
        val thread=Thread{guardedProbeStop({throw IllegalStateException("PRIVATE_SYNTHETIC_MESSAGE")}){kind.set(it)}}
        thread.uncaughtExceptionHandler=Thread.UncaughtExceptionHandler{_,_->uncaught.set(true)}
        thread.start();thread.join(1000);assertFalse(thread.isAlive);assertFalse(uncaught.get())
        assertEquals("IllegalStateException",kind.get())
        var anonymous=""
        guardedProbeStop({throw object:RuntimeException("PRIVATE_SYNTHETIC_MESSAGE") {}}){anonymous=it}
        assertEquals("Throwable",anonymous)
        requireJunitFail(decideProbeResult("DEPENDENCY_FOREGROUND_LOST","","NativeDependency","",anonymous,released))
        val result=decideProbeResult("DEPENDENCY_FOREGROUND_LOST","","NativeDependency","RuntimeException",kind.get()!!,released)
        assertEquals("FAIL",result.outcome);assertTrue(result.junitFailure)
        assertEquals("DEPENDENCY_FOREGROUND_LOST",result.dependencyReason)
        requireJunitFail(result)
        requireJunitFail(decideProbeResult("DEPENDENCY_FOREGROUND_LOST","","NativeDependency","",kind.get()!!,released))
        assertFalse(result.json().contains("PRIVATE_SYNTHETIC_MESSAGE"));println("RESULT_JSON:"+result.json())
    }
    @Test fun cleanupExceptionOverridesDependencyAndProducesActualFailureVerdict(){
        val result=decideProbeResult("DEPENDENCY_RECORD_AUDIO_PERMISSION","","NativeDependency","IllegalStateException","",released)
        assertEquals("FAIL",result.outcome);assertTrue(result.junitFailure);assertEquals("NATIVE_CLEANUP_EXCEPTION",result.reason)
        assertEquals("DEPENDENCY_RECORD_AUDIO_PERMISSION",result.dependencyReason);requireJunitFail(result);println("RESULT_JSON:"+result.json())
    }
    @Test fun anyUnconfirmedResourceOverridesDependency(){
        for(proof in listOf(released.copy(nativeStopped=false),released.copy(nativeReleased=false),released.copy(workerJoined=false),
            released.copy(stopJoined=false),released.copy(ownedLeaseComplete=false))){
            val result=decideProbeResult("DEPENDENCY_FOREGROUND_LOST","","NativeDependency","","",proof)
            assertEquals("FAIL",result.outcome);assertTrue(result.junitFailure);requireJunitFail(result);println("RESULT_JSON:"+result.json())
        }
    }
    @Test fun onlyCleanDependencyMaySkipAndOnlyCleanSuccessMayPass(){
        assertEquals("NOT_RUN_DEPENDENCY",decideProbeResult("DEPENDENCY_DEVICE_LOCKED_OR_NOT_INTERACTIVE","","NativeDependency","","",released).outcome)
        val pass=decideProbeResult("","","","","",released);assertEquals("PASS",pass.outcome);assertFalse(pass.junitFailure);pass.enforce()
        val skip=decideProbeResult("DEPENDENCY_FOREGROUND_LOST","","NativeDependency","","",released)
        assertTrue(runCatching{skip.enforce()}.exceptionOrNull() is org.junit.AssumptionViolatedException)
        val noLease=ProbeReleaseProof(false,false,false,false,false,false)
        assertEquals("NOT_RUN_DEPENDENCY",decideProbeResult("DEPENDENCY_RECORDER_BUSY","","NativeDependency","","",noLease).outcome)
    }
}
