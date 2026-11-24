package com.littlebuddy.v2

import org.junit.Assert.*
import org.junit.Test

class PlaybackTest {
    private class Native : TrackPort {
        var position = 0L
        var writes = 0
        var failStop = false
        var failRelease = false
        val calls = mutableListOf<String>()
        override val head get() = position
        override fun write(pcm: ShortArray, offset: Int): Int { writes += pcm.size-offset; return pcm.size-offset }
        override fun play() { calls += "play" }
        override fun pause() { calls += "pause" }
        override fun mute() { calls += "mute" }
        override fun flush() { calls += "flush" }
        override fun stop() { calls += "stop"; if (failStop) error("stop") }
        override fun release() { calls += "release"; if (failRelease) error("release") }
    }
    private val binding = Binding(1, "native", 3)
    private fun packet(b: Binding = binding) = AudioPacket(b, "s", 0, 100, ShortArray(100) { 5 })

    @Test fun writesDoNotCommitFactsAndActualHeadDoes() {
        val native = Native(); val acks = mutableListOf<PlaybackAck>()
        val player = Playback({ native }, { 0L }, acks::add)
        player.bind(binding); player.enqueue(packet()); player.tick()
        assertEquals(0L, acks.last().head)
        native.position = 50; player.tick()
        assertEquals(50L, acks.last().head)
        native.position = 100; player.tick()
        assertEquals(100L, acks.last().head)
    }
    @Test fun localStopOrderAndLatePackets() {
        val native = Native()
        val player = Playback({ native }, { 0L }, {})
        player.bind(binding); player.enqueue(packet()); player.tick()
        native.calls.clear()
        assertEquals(StopResult(true, true), player.stop())
        assertEquals(listOf("mute", "pause", "flush", "stop", "release"), native.calls)
        assertNull(player.binding)
        val old = packet(); assertFalse(player.enqueue(old)); assertTrue(old.pcm.all { it == 0.toShort() })
    }
    @Test fun stopAndReleaseFailuresQuarantineWithoutSkippingRelease() {
        for (stop in listOf(true, false)) {
            val native = Native().apply { failStop = stop; failRelease = !stop }
            val player = Playback({ native }, { 0L }, {})
            player.bind(binding)
            assertNotEquals(StopResult(true, true), player.stop())
            assertTrue(player.quarantined); assertTrue(native.calls.contains("release"))
            try { player.bind(binding.copy(epoch=2)); fail() } catch (_: IllegalStateException) {}
        }
    }
    @Test fun unchangedHeadAndWritesCannotPostponeStallRelease() {
        val native = Native(); var now = 0L
        val player = Playback({ native }, { now }, {})
        player.bind(binding); player.enqueue(packet()); player.tick()
        now = 59_999; player.tick()
        now = 60_000
        try { player.tick(); fail() } catch (_: IllegalStateException) {}
        assertNull(player.binding); assertTrue(native.calls.contains("release"))
    }
    @Test fun realPartialProgressRenewsClock() {
        val native = Native(); var now = 0L
        val player = Playback({ native }, { now }, {})
        player.bind(binding); player.enqueue(packet()); player.tick()
        now = 50_000; native.position = 20; player.tick()
        now = 60_000; player.tick(); assertEquals(binding, player.binding)
    }
    @Test fun resetHeadCannotReveal() {
        val native = Native(); val acks = mutableListOf<PlaybackAck>()
        val player = Playback({ native }, { 0L }, acks::add)
        player.bind(binding); player.enqueue(packet()); player.tick()
        native.position = 50; player.tick()
        native.position = 0
        try { player.tick(); fail() } catch (_: IllegalStateException) {}
        assertEquals(50L, acks.last().head); assertNull(player.binding)
    }
    @Test fun suspiciousSoundPausesAndOnlyConfirmedNoiseResumes() {
        val calls = mutableListOf<String>()
        val turns = Turns(object : TurnActions {
            override fun suspendOutput() { calls += "pause" }
            override fun stopLocallyAndRevoke() { calls += "stop" }
            override fun resumeConfirmedNoise() { calls += "resume" }
            override fun listen() { calls += "listen" }
            override fun clarify() { calls += "clarify" }
        })
        turns.voiceCandidate(); turns.decide(Meaning.UNKNOWN)
        assertEquals(listOf("pause", "listen", "clarify"), calls)
        calls.clear(); turns.voiceCandidate(); turns.decide(Meaning.STOP)
        assertEquals(listOf("pause", "listen", "stop", "listen"), calls)
        calls.clear(); turns.voiceCandidate(); turns.decide(Meaning.CONFIRMED_NOISE)
        assertEquals(listOf("pause", "listen", "resume"), calls)
    }
}
