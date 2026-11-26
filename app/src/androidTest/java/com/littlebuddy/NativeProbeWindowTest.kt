package com.littlebuddy
import org.junit.Assert.*
import org.junit.Test

class NativeProbeWindowTest {
    @Test fun longSelectionRequiresAllThreeFlagsAndOneExactMethod(){
        fun allowed(m:String?=NativeProbeSelection.LONG,p:String?="true",i:String?="true",l:String?="true")=
            NativeProbeSelection.permits(m,p,i,l,null,null)
        assertTrue(allowed());assertFalse(allowed(p=null));assertFalse(allowed(i="false"));assertFalse(allowed(l=null))
        for(m in listOf(null,"com.littlebuddy.NativeTimestampTest",NativeProbeSelection.LONG+",other",NativeProbeSelection.LONG+" "))assertFalse(allowed(m=m))
        assertTrue(allowed(m=NativeProbeSelection.SHORT,l=null))
        assertFalse(allowed(m=NativeProbeSelection.STARTUP));assertFalse(allowed(m=NativeProbeSelection.CADENCE))
    }
    @Test fun exactDeadlineDoesNotStartAnotherApiAndEarlyCompletionCannotPass(){
        var clock=100L;val window=NativeProbeWindow{clock};var calls=0
        fun attempt(){window.beforeApi(950_000);calls++}
        clock=60_099;attempt();assertEquals(1,calls)
        assertTrue(runCatching{window.requireComplete(950_000,3000)}.isFailure)
        clock=60_100;assertTrue(runCatching{attempt()}.exceptionOrNull() is ProbeWindowEnded)
        assertEquals(1,calls);window.requireComplete(950_000,3000)
    }
    @Test fun frozenClockCannotEvadeSampleCapAndRegressionCannotPass(){
        var clock=10L;val window=NativeProbeWindow{clock}
        window.beforeApi(NativeProbeWindow.SAMPLE_CAP)
        assertTrue(runCatching{window.afterApi(NativeProbeWindow.SAMPLE_CAP+1)}.isFailure)
        clock=9;assertTrue(runCatching{window.beforeApi(0)}.isFailure)
    }
    @Test fun lateApiReturnIsFailureNotSuccessfulWindowEnd(){
        var clock=0L;val window=NativeProbeWindow{clock}
        clock=59_999;window.beforeApi(950_000);clock=60_001
        val failure=runCatching{window.afterApi(950_320)}.exceptionOrNull()
        assertTrue(failure is IllegalStateException);assertFalse(window.ended)
        assertTrue(runCatching{window.requireComplete(950_320,3000)}.isFailure)
    }
    @Test fun reachingTimeWithoutEnoughActualContinuousSamplesIsNotPass(){
        var clock=0L;val window=NativeProbeWindow{clock};clock=60_000
        assertTrue(runCatching{window.beforeApi(0)}.exceptionOrNull() is ProbeWindowEnded)
        for(pair in listOf(0L to 0L,943_999L to 3000L,950_000L to 2899L,968_001L to 3000L))
            assertTrue(runCatching{window.requireComplete(pair.first,pair.second)}.isFailure)
    }
}
