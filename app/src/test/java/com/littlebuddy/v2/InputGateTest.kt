package com.littlebuddy.v2

import org.junit.Assert.*
import org.junit.Test

class InputGateTest {
    private class Lab {
        var time = 0L
        val calls = mutableListOf<String>()
        val gate = InputGate(Waits(), { time }, { calls += "advance:$it" },
            { calls += "probe:$it" }, { calls += "seal:$it" }, { calls += "solo" },
            { calls += "ask" }, { calls += "idle" })
    }
    @Test fun wakeContinuationSealsWithoutExtraSoloProposal() {
        val lab = Lab(); val g = lab.gate
        g.wake(); lab.time = 100; g.speech(); g.quiet()
        g.decision(1, Completion.COMPLETE)
        lab.time = 1100; g.tick(false); lab.time = 1200; g.tick(false)
        assertEquals(listOf("advance:1", "seal:1"), lab.calls)
    }
    @Test fun soloWakeProposesExactlyOnce() {
        val lab = Lab(); lab.gate.wake()
        lab.time = 500; lab.gate.tick(false); lab.time = 900; lab.gate.tick(false)
        assertEquals(listOf("solo"), lab.calls)
    }
    @Test fun incompleteRechecksAndThinkingInvitesOnceWithoutSealing() {
        val lab = Lab(); val g = lab.gate
        g.wake(); g.speech(); g.quiet(); g.decision(1, Completion.INCOMPLETE)
        lab.time = 2500; g.tick(false)
        assertTrue(lab.calls.contains("probe:1")); assertFalse(lab.calls.contains("seal:1"))
        g.decision(1, Completion.THINKING)
        lab.time = 12500; g.tick(false); lab.time = 22500; g.tick(false)
        assertEquals(1, lab.calls.count { it == "ask" }); assertFalse(lab.calls.any { it.startsWith("seal") })
    }
    @Test fun continuationSupersedesDelayedCompleteDecision() {
        val lab = Lab(); val g = lab.gate
        g.wake(); g.speech(); g.quiet(); lab.time = 300; g.tick(false)
        lab.time = 600; g.speech(); g.quiet()
        g.decision(1, Completion.COMPLETE); lab.time = 2000; g.tick(false)
        assertFalse(lab.calls.contains("seal:1")); assertFalse(lab.calls.contains("seal:2"))
        g.decision(2, Completion.COMPLETE); g.tick(false)
        assertTrue(lab.calls.contains("seal:2"))
    }
    @Test fun idleAtSixtySecondsDoesNotEndBackendRetentionAndBusyOutputExcludesIdle() {
        val lab = Lab(); val g = lab.gate
        g.wake(); lab.time = 60000; g.tick(true); assertTrue(g.awake)
        g.tick(false); assertFalse(g.awake); assertTrue(lab.calls.contains("idle"))
    }
    @Test fun absoluteKwsTailCopiesPreserveFirstSamplesUnderOwnerDelay() {
        val ring = WakeSamples(16000)
        // Real production ring, known KWS tail at sample 1000; intent starts at 1001.
        val all = ShortArray(6000) { it.toShort() }
        for (start in 0 until 1920 step 320) ring.push(all.copyOfRange(start,start+320),320)
        ring.begin(1000, preRoll=0)
        val delayedOwnerQueue = ring.read()
        // Simulate another 240ms of capture before the owner dispatches the copies.
        for (start in 1920 until 5760 step 320) ring.push(all.copyOfRange(start,start+320),320)
        val resumed = ring.read()
        val emitted = (delayedOwnerQueue + resumed).flatMap { it.toList() }
        assertEquals((1000 until 5760).map { it.toShort() }, emitted)
        assertTrue(ring.read().isEmpty()) // No duplicate handoff on a second dispatch.
    }
    @Test fun delayedKwsTailReplaysIntoProductionVadBeforeNextCaptureRead() {
        val buffer = WakeSamples()
        val samples = ShortArray(6400) { if (it < 3200) 0 else if (it % 2 == 0) 1500 else -1500 }
        for (start in 0 until 6400 step 320) buffer.push(samples.copyOfRange(start,start+320),320)
        buffer.begin(3200, preRoll=0)
        val detector = com.littlebuddy.SpeechDetector(320, initialFloor=36.0)
        var detected = false
        buffer.inspectAfter(3200) { cached ->
            detector.accept(cached,cached.size)
            detected = detected || detector.detectedSpeechInRead
        }
        assertTrue(detected) // No future frame, no eight-window calibration loss.
        val ownerDelayedCopies = buffer.read().flatMap { it.toList() }
        assertEquals(samples.drop(3200), ownerDelayedCopies)
        assertTrue(buffer.read().isEmpty())
    }
    @Test fun distinctWaitParametersAreValidated() {
        assertEquals(900L, Waits(complete=900,incomplete=2200,thinking=9000).complete)
        try { Waits(complete=1500); fail() } catch (_: IllegalArgumentException) {}
    }
    @Test fun capturedTimeIncludesOwnerDelayAndCannotBeInTheFuture() {
        val lab=Lab();lab.gate.wake();lab.time=6000
        lab.gate.speech(0);lab.gate.quiet()
        assertEquals(15000L,lab.gate.responseDeadline)
        lab.time=14000;lab.gate.decision(1,Completion.COMPLETE);lab.gate.tick(true)
        assertEquals(15000L,lab.gate.responseDeadline)
        lab.time=15000
        try{lab.gate.checkResponseDeadline();fail()}catch(_:IllegalStateException){}
        try{lab.gate.speech(16000);fail()}catch(_:IllegalArgumentException){}
    }
    @Test fun partialAcknowledgementCannotReleaseBudgetButEffectivePlayedCan() {
        val lab=Lab();lab.gate.wake();lab.gate.speech();lab.gate.quiet()
        lab.time=14999;lab.gate.checkResponseDeadline()
        lab.gate.effectivePlayed();lab.time=16000;lab.gate.checkResponseDeadline()
    }

}
