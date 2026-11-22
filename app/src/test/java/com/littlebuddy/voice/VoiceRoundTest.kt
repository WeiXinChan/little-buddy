package com.littlebuddy.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class VoiceRoundTest {
    private class Fixture(singleTurn: Boolean = false) : AudioPort, ReplyPort, Deadline {
        private var now = 0L
        private val timers = mutableListOf<Pair<Long, () -> Unit>>()
        val endpoints = mutableListOf<Long>()
        val round = VoiceRound(this, this, this, singleTurn,
            captureSealed = { id, _ -> endpoints += id }) { _, _ -> }
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
        override fun playStream(operation: Long, stream: PcmStream) { plays += operation }
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

    @Test fun singleTurnPlaysSegmentsInOrderThenWaitsForAnotherClick() = with(Fixture(singleTurn = true)) {
        round.start()
        val id = submit()
        round.segment(id, first)
        round.segment(id, first.copy(number = 2))
        round.endReply(id, 2)
        assertEquals(1, plays.size)
        drain()
        assertEquals(2, plays.size)
        drain()
        assertEquals(VoiceRound.Phase.IDLE, phase)
        assertEquals(1, captures.size)
        round.start()
        round.replyFailed(id)
        assertEquals(VoiceRound.Phase.OPENING, phase)
        assertEquals(2, captures.size)
    }

    @Test fun streamCleanupAndLateCaptureCallbacksDoNotEmitAnotherEndpoint() = with(Fixture(true)) {
        val source = object : PcmStream {
            override val ended = false
            override val aborted = false
            override fun poll(): ShortArray? = null
            override fun playbackRequested(operation: Long) = Unit
            override fun playbackHeadAdvanced(operation: Long) = Unit
        }
        round.start()
        val turn = submit()
        val capture = captures.single()
        round.endCapture(capture)
        round.stream(turn, 1, source)
        round.stream(turn, 2, source)
        assertEquals(1, plays.size)
        round.foreground(false)
        round.foreground(true)
        round.start()
        round.released(plays.single())
        round.stream(turn, 2, source)
        round.endReply(turn, 2)
        assertEquals(listOf(capture), endpoints)
        assertEquals(1, plays.size)
        assertEquals(2, captures.size)
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
        assertEquals(VoiceRound.ReplyTimeout.FIRST_SEGMENT, round.replyTimeout)
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
        assertEquals(VoiceRound.ReplyTimeout.INCOMPLETE_REPLY, round.replyTimeout)
        round.endReply(id, 1)
        assertEquals(listOf(id), cancels)
        assertEquals(0, round.completed)
    }

    @Test fun cancelledRoundDeadlinesCannotChangeNewWaitingRound() = with(Fixture()) {
        round.start()
        val old = submit()
        round.segment(old, first)
        drain()
        advance(1_000)
        round.stop()
        assertEquals(null, round.replyTimeout)
        advance(1_000)
        round.start()
        val current = submit()
        advance(6_000)
        assertEquals(null, round.replyTimeout)
        assertEquals(VoiceRound.Phase.WAITING, phase)
        assertEquals(listOf(old), cancels)
        round.segment(current, first)
        round.endReply(current, 1)
        drain()
        assertEquals(null, round.replyTimeout)
        assertEquals(VoiceRound.Phase.OPENING, phase)
    }

    @Test fun startClearsTimeoutAndManualEndOfSilenceDoesNotSetIt() = with(Fixture()) {
        round.start()
        submit()
        advance(8_000)
        assertEquals(VoiceRound.ReplyTimeout.FIRST_SEGMENT, round.replyTimeout)
        round.start()
        assertEquals(null, round.replyTimeout)
        val capture = captures.last()
        round.captureFrame(capture, false)
        round.endCapture(capture)
        round.released(capture)
        assertEquals(VoiceRound.Phase.IDLE, phase)
        assertEquals(null, round.replyTimeout)
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
        assertEquals(VoiceRound.EmptyCapture.NO_SPEECH, round.emptyCapture)
        assertEquals(VoiceRound.CaptureEnd.MANUAL, round.captureEnd)
        assertEquals(VoiceRound.Phase.IDLE, phase)
    }

    @Test fun missingFramesAndFramesWithoutSpeechUseDifferentDeadlines() = with(Fixture()) {
        round.start()
        val missing = captures.last()
        advance(2_999)
        assertEquals(VoiceRound.Phase.OPENING, phase)
        advance(1)
        round.captureFrame(missing, true)
        round.released(missing)
        assertEquals(VoiceRound.EmptyCapture.NO_FRAMES, round.emptyCapture)
        assertEquals(VoiceRound.CaptureEnd.NO_FRAME_TIMEOUT, round.captureEnd)

        round.start()
        val quiet = captures.last()
        round.captureFrame(quiet, false)
        advance(3_000)
        assertEquals(VoiceRound.Phase.LISTENING, phase)
        advance(17_000)
        round.released(quiet)
        assertEquals(VoiceRound.EmptyCapture.NO_SPEECH, round.emptyCapture)
        assertEquals(VoiceRound.CaptureEnd.MAX_DURATION, round.captureEnd)
        assertEquals(emptyList<Turn>(), requests)
    }

    @Test fun oldDeadlineCannotEndNewCaptureAndMaximumDurationSubmitsSpeech() = with(Fixture()) {
        round.start()
        val old = captures.last()
        round.captureFrame(old, true)
        advance(1_000)
        round.start()
        round.released(old)
        val current = captures.last()
        round.captureFrame(current, true)
        advance(19_000)
        assertEquals(VoiceRound.Phase.LISTENING, phase)
        advance(1_000)
        assertEquals(VoiceRound.CaptureEnd.MAX_DURATION, round.captureEnd)
        assertEquals(emptyList<Turn>(), requests)
        round.released(current)
        assertEquals(1, requests.size)
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
