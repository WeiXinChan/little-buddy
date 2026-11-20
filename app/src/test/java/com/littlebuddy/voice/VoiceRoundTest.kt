package com.littlebuddy.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class VoiceRoundTest {
    private class Fixture : AudioPort, ReplyPort, Deadline {
        private var now = 0L
        private val timers = mutableListOf<Pair<Long, () -> Unit>>()
        val round = VoiceRound(this, this, this) { _, _ -> }
        val captures = mutableListOf<Long>()
        val plays = mutableListOf<Long>()
        val stops = mutableListOf<Long>()
        val requests = mutableListOf<Turn>()
        val cancels = mutableListOf<Turn>()
        val phase get() = round.phase
        val first = Segment(1, shortArrayOf(1))

        init { round.foreground(true) }

        override fun capture(operation: Long) { captures += operation }
        override fun play(operation: Long, samples: ShortArray) { plays += operation }
        override fun stop(operation: Long) { stops += operation }
        override fun request(turn: Turn) { requests += turn }
        override fun cancel(turn: Turn) { cancels += turn }
        override fun after(milliseconds: Long, action: () -> Unit) {
            timers += (now + milliseconds) to action
        }

        fun advance(ms: Long) {
            val target = now + ms
            while (true) {
                val next = timers.minByOrNull { it.first } ?: break
                if (next.first > target) break
                timers.remove(next)
                now = next.first
                next.second()
            }
            now = target
        }

        fun submit(): Turn {
            val id = captures.last()
            round.captureFrame(id, true)
            round.endCapture(id)
            round.released(id)
            return requests.last()
        }

        fun drain() {
            val id = plays.last()
            round.played(id)
            round.released(id)
        }
    }

    @Test fun pendingOpenKeepsItsSlotAndBackgroundDiscardsQueuedStart() = with(Fixture()) {
        round.start()
        val old = captures.single()
        round.start()
        round.captureFrame(old, true)
        assertEquals(VoiceRound.Phase.CLEANING, phase)
        assertEquals(listOf(old), captures)
        round.foreground(false)
        round.foreground(true)
        round.released(old)
        assertEquals(listOf(old), captures)
        assertEquals(VoiceRound.Phase.IDLE, phase)
    }

    @Test fun oldReplyAndReleaseCannotAffectNewRound() = with(Fixture()) {
        round.start()
        val old = submit()
        round.segment(old, first)
        val oldAudio = plays.single()
        round.stop()
        round.start()
        assertEquals(1, captures.size)
        round.released(oldAudio)
        val current = submit()
        round.segment(old, first)
        round.endReply(old, 1)
        round.released(oldAudio)
        assertNotEquals(old, current)
        assertEquals(listOf(old), cancels)
        assertEquals(listOf(oldAudio), plays)
        assertEquals(VoiceRound.Phase.WAITING, phase)
    }

    @Test fun outOfOrderSegmentCancelsWithoutAdvancingGame() = with(Fixture()) {
        round.start(game = true)
        val id = submit()
        round.segment(id, first.copy(number = 2))
        round.endReply(id, 2)
        assertEquals(listOf(id), cancels)
        assertEquals(0, plays.size)
        assertEquals(0, round.completed)
    }

    @Test fun firstPacketTimeoutDiscardsLateReply() = with(Fixture()) {
        round.start()
        val id = submit()
        advance(8_000)
        round.segment(id, first)
        assertEquals(listOf(id), cancels)
        assertEquals(0, plays.size)
        assertEquals(VoiceRound.Phase.IDLE, phase)
    }

    @Test fun stalledTailTimesOutAndDoesNotCountPartialPlayback() = with(Fixture()) {
        round.start(game = true)
        val id = submit()
        round.segment(id, first)
        drain()
        advance(4_000)
        round.endReply(id, 1)
        assertEquals(listOf(id), cancels)
        assertEquals(0, round.completed)
    }

    @Test fun countRequiresFinalDeclarationAndEverySegmentToDrain() = with(Fixture()) {
        round.start(game = true)
        repeat(3) { index ->
            val id = submit()
            round.segment(id, first)
            round.segment(id, first.copy(number = 2))
            if (index % 2 == 0) round.endReply(id, 2)
            drain()
            assertEquals(index, round.completed)
            drain()
            if (index % 2 != 0) {
                assertEquals(index, round.completed)
                round.endReply(id, 2)
            }
            round.endReply(id, 2)
            assertEquals(index + 1, round.completed)
        }
        assertEquals(VoiceRound.Phase.IDLE, phase)
        assertEquals(3, captures.size)
    }

    @Test fun unconfirmedReleaseTimesOutWithoutFreeingSlot() = with(Fixture()) {
        round.start()
        val old = captures.single()
        round.start()
        advance(2_000)
        assertEquals(VoiceRound.Phase.UNAVAILABLE, phase)
        round.start()
        assertEquals(listOf(old), captures)
        round.released(old)
        assertEquals(VoiceRound.Phase.IDLE, phase)
        round.start()
        assertEquals(2, captures.size)
    }

    @Test fun silenceDoesNotRequestReply() = with(Fixture()) {
        round.start()
        val id = captures.single()
        round.captureFrame(id, false)
        round.endCapture(id)
        round.released(id)
        assertEquals(emptyList<Turn>(), requests)
        assertEquals(VoiceRound.Phase.IDLE, phase)
    }

    @Test fun simulatedServiceCompletesOneRoundOnTheProductionCoordinator() = with(Fixture()) {
        lateinit var coordinator: VoiceRound
        val reply = SimulatedReply(this, { id, segment -> coordinator.segment(id, segment) },
            { id, last -> coordinator.endReply(id, last) })
        coordinator = VoiceRound(this, reply, this) { _, _ -> }
        coordinator.foreground(true)
        coordinator.start(game = true)
        val capture = captures.single()
        coordinator.captureFrame(capture, true)
        coordinator.endCapture(capture)
        coordinator.released(capture)
        assertEquals(VoiceRound.Phase.WAITING, coordinator.phase)
        advance(250)
        assertEquals(VoiceRound.Phase.PLAYING, coordinator.phase)
        val playback = plays.single()
        coordinator.played(playback)
        coordinator.released(playback)
        assertEquals(1, coordinator.completed)
        assertEquals(VoiceRound.Phase.OPENING, coordinator.phase)
    }
}
