package com.littlebuddy

import org.junit.Assert.*
import org.junit.AssumptionViolatedException
import org.junit.Test

/** Actual window -> shared catch classifier -> actual result/enforce chain, no Android/native fake PASS. */
class NativeProbeClassificationTest {
    private class Dependency(val code:String):AssumptionViolatedException(code)
    private val released=ProbeReleaseProof(true,true,true,true,true,true)
    private fun classify(error:Throwable,cancelled:Boolean=false,foreground:Boolean=true)=
        classifyNativeProbeFailure(error,{cancelled || !foreground},::Dependency)
    private fun decision(error:Throwable,proof:ProbeReleaseProof=released):ProbeDecision {
        val dep=(error as? Dependency)?.code ?: ""
        val reason=(error as? ProbeInvariantFailure)?.invariant?.safeReason ?: if(dep.isEmpty())"NATIVE_PROBE_FAILED" else ""
        return decideProbeResult(dep,reason,probeFailureClass(error),"","",proof)
    }
    private fun assertActualFail(error:Throwable) {
        val result=decision(error)
        assertEquals("FAIL",result.outcome);assertTrue(result.junitFailure)
        val thrown=runCatching{result.enforce()}.exceptionOrNull()
        assertTrue(thrown is AssertionError);assertFalse(thrown is AssumptionViolatedException)
    }
    @Test fun deadlineWitnessSurvivesCancellationBeforeAfterOrAtReturn(){
        for(order in listOf("cancel_during_api","cancel_after_violation","cancel_at_return")) {
            var now=0L;var cancelled=false;var cancelAtClockRead=false
            val window=NativeProbeWindow{if(cancelAtClockRead)cancelled=true;now}
            now=59_999;window.beforeApi(950_000)
            if(order=="cancel_during_api")cancelled=true
            now=60_001
            if(order=="cancel_at_return")cancelAtClockRead=true
            val actual=runCatching{window.afterApi(950_320)}.exceptionOrNull()!!
            if(order=="cancel_after_violation")cancelled=true
            assertTrue(cancelled);assertEquals(ProbeInvariant.API_CROSSED_DEADLINE,(actual as ProbeInvariantFailure).invariant)
            assertSame(actual,classify(actual,cancelled));assertActualFail(classify(actual,cancelled))
            assertActualFail(classify(actual,foreground=false))
        }
    }
    @Test fun aCleanPreExistingDependencyRemainsAnActualSkip(){
        val original=Dependency("DEPENDENCY_FOREGROUND_LOST")
        val result=decision(classify(original,cancelled=true))
        assertEquals("NOT_RUN_DEPENDENCY",result.outcome);assertFalse(result.junitFailure)
        assertTrue(runCatching{result.enforce()}.exceptionOrNull() is AssumptionViolatedException)
    }
    @Test fun allObservedWindowInvariantsKeepFailPriority(){
        var now=10L;val regressed=NativeProbeWindow{now};now=9
        val errors=listOf(
            runCatching{regressed.beforeApi(0)}.exceptionOrNull()!!,
            runCatching{NativeProbeWindow{0L}.afterApi(NativeProbeWindow.SAMPLE_CAP+1)}.exceptionOrNull()!!,
            runCatching{NativeProbeWindow{0L}.requireComplete(0,0)}.exceptionOrNull()!!)
        for(error in errors){assertTrue(error is ProbeInvariantFailure);assertActualFail(classify(error,true,false))}
    }
    @Test fun shortProbeUntypedCancellationAndSecurityPolicyAreUnchanged(){
        val native=IllegalStateException("PRIVATE_SYNTHETIC_MESSAGE")
        assertSame(native,classify(native));assertActualFail(classify(native))
        assertEquals("DEPENDENCY_FOREGROUND_LOST",(classify(native,true) as Dependency).code)
        assertEquals("DEPENDENCY_FOREGROUND_LOST",(classify(native,foreground=false) as Dependency).code)
        assertEquals("DEPENDENCY_NATIVE_PERMISSION_OR_POLICY",(classify(SecurityException()) as Dependency).code)
        assertEquals("DEPENDENCY_FOREGROUND_LOST",(classify(SecurityException(),true) as Dependency).code)
    }
    @Test fun witnessedInvariantDoesNotEvenConsultSubsequentDependencyState(){
        val original=ProbeInvariantFailure(ProbeInvariant.API_CROSSED_DEADLINE)
        val classified=classifyNativeProbeFailure(original,
            {throw IllegalStateException("PRIVATE_SYNTHETIC_MESSAGE")},
            {throw IllegalStateException("PRIVATE_SYNTHETIC_MESSAGE")})
        assertSame(original,classified);assertActualFail(classified)
    }
    @Test fun nativeMessageCannotForgeInvariantType(){
        for(invariant in ProbeInvariant.entries){
            val forged=IllegalStateException(invariant.safeReason)
            assertTrue(classify(forged,true) is Dependency)
            assertSame(forged,classify(forged))
        }
    }
    @Test fun cleanupRemainsHigherPriorityThanAnObservedWindowFailure(){
        val actual=ProbeInvariantFailure(ProbeInvariant.API_CROSSED_DEADLINE)
        val unconfirmed=decision(classify(actual,true),released.copy(workerJoined=false))
        assertEquals("NATIVE_CLEANUP_UNCONFIRMED",unconfirmed.reason);assertTrue(unconfirmed.junitFailure)
        val stop=decideProbeResult("",actual.invariant.safeReason,probeFailureClass(actual),"","IllegalStateException",released)
        assertEquals("NATIVE_STOP_REQUEST_FAILED",stop.reason);assertTrue(stop.junitFailure)
        assertTrue(runCatching{stop.enforce()}.exceptionOrNull() is AssertionError)
    }
}
