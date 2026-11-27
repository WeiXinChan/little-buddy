package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
class KeywordTailTest {
    @Test fun actualNativeGlobalTailDoesNotExpireAfterIdle() {
        // Values are actual source-patched core results, not reference-based correction.
        for((prefix,last,fed) in listOf(Triple(0,0.7999999523162842,17920L),Triple(30,30.799999237060547,499200L),Triple(90,90.79999542236328,1461760L))) {
            val tail=KeywordTail.sample(0.0,last,fed)
            assertTrue(tail>prefix*16000 && tail<=fed)
            var now=100000+fed/16+3500;var solos=0
            val gate=InputGate(Waits(),{now},{},{},{},{solos++},{},{})
            gate.wake(100000+tail/16);gate.tick(false)
            assertEquals(1,solos);assertTrue(gate.responseDeadline>now)
        }
    }
    @Test fun oldObservedLocalCoordinateStillReproducesRealDeadlineFailure() {
        var now=100000L+499200/16+3500
        val gate=InputGate(Waits(),{now},{},{},{},{},{},{})
        gate.wake(100000+33920/16)
        assertTrue(runCatching{gate.tick(false)}.isFailure)
    }
    @Test fun invalidOrUnpatchedStartDoesNotBorrowCurrentRead() {
        for(pair in listOf(1.0 to 0.8,0.0 to Double.NaN,0.0 to Double.POSITIVE_INFINITY,-1.0 to 1.0,0.0 to -1.0,0.0 to 20.0))
            assertTrue(runCatching{KeywordTail.sample(pair.first,pair.second,320)}.isFailure)
        assertTrue(runCatching{KeywordTail.sample(0.0,0.8,0)}.isFailure)
    }
    @Test fun captureReWakeOriginKeepsFirstAlreadyPushedFrame() {
        val capturePosition=16000L+320
        val streamBase=wakeOrigin(capturePosition,320)
        assertEquals(16000L,streamBase)
        val local=KeywordTail.sample(0.0,0.8,17920)
        assertEquals(16000L+local,Math.addExact(streamBase,local))
    }
}
