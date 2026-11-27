package com.littlebuddy.v2

import org.junit.Assert.*
import org.junit.Test

class ClockBridgeTest {
    private class Rig {
        var now=1000L; var offset=0L; var bootDelay=0L
        var stamp=CaptureStamp(0,1_000_000_000)
        val ledger=NativeReadLedger(3200,{now},{now+=bootDelay;bootDelay=0;now+offset}){stamp}
        fun ready(){ledger.beginStartup();now=1021;stamp=CaptureStamp(320,1_020_200_000);ledger.stageRead(320)
            now=1041;stamp=CaptureStamp(640,1_040_200_000);ledger.stageRead(320);ledger.finishStartup()}
    }
    @Test fun runtimeNineMsSchedulingIsNotClockChange(){
        val r=Rig();r.ready();r.now=1046;r.bootDelay=9;r.ledger.check()
        assertEquals(640,r.ledger.readSamples.toInt())
    }
    @Test fun realNineMsBootShiftStillFails(){
        val r=Rig();r.ready();r.offset=9
        val e=runCatching{r.ledger.check()}.exceptionOrNull() as CaptureClockFailure
        assertEquals(CaptureClockReason.TIMEBASE_CHANGED,e.reason)
    }

    @Test fun originSchedulingDoesNotBecomePermanentOffsetError(){
        var now=1000L;var first=true
        val ledger=NativeReadLedger(3200,{now},{if(first){now+=9;first=false};now}){CaptureStamp(0,now*1_000_000)}
        ledger.check();assertTrue(ledger.sampleTime(0)<=now-6)
    }
    @Test fun bracketContainsActualOffsetIncludingFloorQuantization(){
        var n=1000L;val b=CaptureClockBridge({n},{n+100})
        assertEquals(99L,b.origin.lower);assertEquals(101L,b.origin.upper)
        n=2000;b.check(n);assertEquals(2094L,b.earliestBoot(2000))
    }
    @Test fun persistentWideWindowsAreNotAcceptedAsNoSuspend(){
        var n=1000L;var delay=0L
        val b=CaptureClockBridge({n},{n+=delay;n})
        delay=9
        val e=runCatching{b.check(n)}.exceptionOrNull() as CaptureClockFailure
        assertEquals(CaptureClockReason.TIMEBASE_UNCERTAIN,e.reason);assertEquals(2,b.attempts)
    }
    @Test fun wideWindowThenRealSuspendRemainsFailure(){
        var n=1000L;var delay=0L;var shift=0L
        val b=CaptureClockBridge({n},{val d=delay;delay=0;n+=d;n+shift})
        delay=9;shift=9
        val e=runCatching{b.check(n)}.exceptionOrNull() as CaptureClockFailure
        assertEquals(CaptureClockReason.TIMEBASE_CHANGED,e.reason)
    }
    @Test fun positiveAndNegativeShiftCannotBeHiddenByFreshOrigin(){
        for(shift in listOf(-9L,9L)){
            val r=Rig();r.ready();r.offset=shift
            assertEquals(CaptureClockReason.TIMEBASE_CHANGED,(runCatching{r.ledger.check()}.exceptionOrNull() as CaptureClockFailure).reason)
            assertEquals(640L,r.ledger.readSamples)
        }
    }
    @Test fun bootSamplingDelayCountsAgainstTimestampAge(){
        val r=Rig();r.ready();r.now=1050;r.bootDelay=100
        val e=runCatching{r.ledger.check()}.exceptionOrNull() as CaptureClockFailure
        assertEquals(CaptureClockReason.TIMESTAMP_STALE,e.reason)
        assertEquals(1050L,e.evidence.apiAfterMs);assertEquals(1150L,e.evidence.bridgeAfterMs)
        assertEquals(109_800_000L,e.evidence.ageNs)
    }
    @Test fun samplingDelayCannotEraseUnreadAudioBudget(){
        val r=Rig();r.ready();r.now=1046;r.bootDelay=170
        r.stamp=CaptureStamp(640,1_040_200_000)
        val e=runCatching{r.ledger.check()}.exceptionOrNull() as CaptureClockFailure
        assertEquals(CaptureClockReason.TIMESTAMP_STALE,e.reason)
        assertEquals(640L,r.ledger.readSamples)
    }
    @Test fun mappingIsEarliestAndNeverRebasedByLaterBootObservation(){
        val r=Rig();r.ready();val before=r.ledger.sampleTime(0)
        r.offset=2;r.now=1042;r.ledger.check()
        assertEquals(before,r.ledger.sampleTime(0))
        // phase and fixed initial offset lower bound, plus original 1ms final rounding.
        assertEquals(991L,before)
    }
    @Test fun bridgeMonotonicRegressionIsTypedFailure(){
        var n=1000L;var reverse=false
        val b=CaptureClockBridge({n},{if(reverse)n-=1;n})
        reverse=true
        assertEquals(CaptureClockReason.CLOCK_REGRESSED,(runCatching{b.check(1000)}.exceptionOrNull() as CaptureClockFailure).reason)
    }
    @Test fun constructorCannotHideUnboundedClockSampling(){
        var n=0L
        val e=runCatching{CaptureClockBridge({n},{n+=9;n})}.exceptionOrNull() as CaptureClockFailure
        assertEquals(CaptureClockReason.TIMEBASE_UNCERTAIN,e.reason)
    }

    @Test fun wholeIntervalMustFitFiveMsNotJustItsNearestEndpoint(){
        for(shift in listOf(-3L,3L)) {val r=Rig();r.ready();r.offset=shift;r.ledger.check()}
        for(shift in listOf(-4L,4L)) {
            val r=Rig();r.ready();r.offset=shift
            assertEquals(CaptureClockReason.TIMEBASE_UNCERTAIN,(runCatching{r.ledger.check()}.exceptionOrNull() as CaptureClockFailure).reason)
        }
    }
    @Test fun clockShiftMustNotBeAmortizedAcrossSuccessiveChecks(){
        val r=Rig();r.ready()
        for(i in 1L..3L){r.offset=i;r.ledger.check()}
        r.offset=4
        assertEquals(CaptureClockReason.TIMEBASE_UNCERTAIN,(runCatching{r.ledger.check()}.exceptionOrNull() as CaptureClockFailure).reason)
    }

    @Test fun schedulingCanExhaustNativeRoomEvenWithFreshTimestamp(){
        val r=Rig();r.ready();r.now=1160;r.stamp=CaptureStamp(2560,1_160_200_000);r.bootDelay=70
        val e=runCatching{r.ledger.check()}.exceptionOrNull() as CaptureClockFailure
        assertEquals(CaptureClockReason.CUMULATIVE_NATIVE_CONTINUITY_EXHAUSTED,e.reason)
        assertEquals(640L,r.ledger.readSamples);assertTrue(e.evidence.conservativeAgeNs<100_000_000)
    }

    @Test fun scheduleAfterInitialBootReadDoesNotCorruptPermanentMapping(){
        var now=1000L;var pending=0L;var first=true
        val ledger=NativeReadLedger(3200,{now+=pending;pending=0;now},{
            val result=now;if(first){first=false;pending=9};result
        }){CaptureStamp(0,now*1_000_000)}
        ledger.check();assertEquals(1009L,now)
        assertTrue(ledger.sampleTime(0)<=1002L)
    }
}
