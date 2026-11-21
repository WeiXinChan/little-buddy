package com.littlebuddy.voice

data class Segment(val number: Int, val samples: ShortArray)
data class Turn(val session: Long, val number: Long)

interface AudioPort {
    // Completions must be posted to the coordinator's serial dispatcher.
    // Capture signals only metadata. No microphone samples are sent to the simulated service.
    fun capture(operation: Long)
    fun play(operation: Long, samples: ShortArray)
    // Immediately mute playback. Report released only when the matching operation
    // has no active or pending handle, including a cancelled asynchronous open.
    fun stop(operation: Long)
}

interface ReplyPort {
    fun request(turn: Turn)
    fun cancel(turn: Turn)
}

fun interface Deadline {
    fun after(milliseconds: Long, action: () -> Unit)
}

// All entry points, including deadline callbacks, must run on one serial dispatcher.
// Audio and reply port callbacks must be posted, never invoked inline.
class VoiceRound(
    private val audio: AudioPort,
    private val replies: ReplyPort,
    private val deadline: Deadline,
    private val changed: (Phase, Int) -> Unit,
) {
    enum class Phase { INACTIVE, IDLE, OPENING, LISTENING, WAITING, PLAYING, CLEANING, UNAVAILABLE }
    enum class ReplyTimeout { FIRST_SEGMENT, INCOMPLETE_REPLY }

    enum class CaptureEnd { MANUAL, TAIL_SILENCE, NO_FRAME_TIMEOUT, MAX_DURATION }
    enum class EmptyCapture { NO_FRAMES, NO_SPEECH }

    var captureEnd: CaptureEnd? = null
        private set

    var emptyCapture: EmptyCapture? = null
        private set

    var replyTimeout: ReplyTimeout? = null
        private set

    private enum class Release { SUBMIT, ADVANCE, IDLE }
    var phase = Phase.INACTIVE
        private set
    var completed = 0
        private set
    private var foreground = false
    private var session = 0L
    private var number = 0L
    private var nextOperation = 0L
    private var operation: Long? = null
    private var turn: Turn? = null
    private var restart = false
    private var speech = false
    private var release: Release? = null
    private var nextSegment = 1
    private var finalSegment: Int? = null
    private val pending = ArrayDeque<Segment>()
    private var playing = false
    private var game = false

    fun foreground(active: Boolean) {
        if (foreground == active) return
        foreground = active
        if (active && operation == null) update(Phase.IDLE)
        if (!active) stop()
    }

    fun start(game: Boolean = false) {
        if (!foreground || phase == Phase.UNAVAILABLE) return
        stop()
        this.game = game
        if (operation == null) openCapture() else restart = true
    }

    fun stop() = stop(null)

    private fun stop(timeout: ReplyTimeout?) {
        captureEnd = null
        emptyCapture = null
        replyTimeout = timeout
        val old = turn
        turn = null
        restart = false
        pending.clear()
        playing = false
        completed = 0
        game = false
        session++
        number = 0
        if (operation != null) releaseAudio(Release.IDLE)
        else update(if (foreground) Phase.IDLE else Phase.INACTIVE)
        if (old != null) replies.cancel(old)
    }

    fun captureFrame(id: Long, hasSpeech: Boolean) {
        if (operation != id || phase !in setOf(Phase.OPENING, Phase.LISTENING)) return
        speech = speech || hasSpeech
        if (phase == Phase.OPENING) update(Phase.LISTENING)
    }

    fun endCapture(id: Long? = operation, reason: CaptureEnd = CaptureEnd.MANUAL) {
        if (id == null || id != operation) return
        when (phase) {
            Phase.OPENING -> {
                captureEnd = reason
                emptyCapture = EmptyCapture.NO_FRAMES
                releaseAudio(Release.IDLE)
            }
            Phase.LISTENING -> {
                captureEnd = reason
                if (!speech) emptyCapture = EmptyCapture.NO_SPEECH
                releaseAudio(if (speech) Release.SUBMIT else Release.IDLE)
            }
            else -> Unit
        }
    }

    fun audioFailed(id: Long) {
        if (id == operation && release == null) stop()
    }

    fun released(id: Long) {
        if (operation != id) return
        val continuation = release ?: return
        operation = null
        release = null
        playing = false
        if (!foreground) {
            update(Phase.INACTIVE)
            return
        }
        when (continuation) {
            Release.SUBMIT -> requestReply()
            Release.ADVANCE -> advance()
            Release.IDLE -> {
                update(Phase.IDLE)
                if (restart) {
                    restart = false
                    openCapture()
                }
            }
        }
    }

    fun segment(id: Turn, segment: Segment) {
        if (!receives(id)) return
        if (finalSegment != null || segment.number != nextSegment ||
            segment.samples.isEmpty() || segment.samples.size > 240_000 ||
            nextSegment > 8
        ) {
            stop()
            return
        }
        nextSegment++
        pending.addLast(segment)
        advance()
    }

    fun endReply(id: Turn, last: Int) {
        if (!receives(id)) return
        if (last < 1 || last != nextSegment - 1 || (finalSegment != null && finalSegment != last)) {
            stop()
            return
        }
        finalSegment = last
        advance()
    }

    fun played(id: Long) {
        if (operation == id && playing && release == null) releaseAudio(Release.ADVANCE)
    }

    private fun receives(id: Turn) = turn == id && release != Release.IDLE

    private fun openCapture() {
        captureEnd = null
        speech = false
        val id = ++nextOperation
        operation = id
        update(Phase.OPENING)
        audio.capture(id)
        deadline.after(3_000) {
            if (operation == id && phase == Phase.OPENING) endCapture(id, CaptureEnd.NO_FRAME_TIMEOUT)
        }
        deadline.after(20_000) {
            if (operation == id && phase == Phase.LISTENING) endCapture(id, CaptureEnd.MAX_DURATION)
        }
    }

    private fun releaseAudio(next: Release) {
        val id = checkNotNull(operation)
        if (release != null) {
            release = next
            return
        }
        release = next
        update(Phase.CLEANING)
        audio.stop(id)
        deadline.after(2_000) {
            if (operation == id && release != null) {
                stop()
                update(Phase.UNAVAILABLE)
            }
        }
    }

    private fun requestReply() {
        val id = Turn(session, ++number)
        turn = id
        nextSegment = 1
        finalSegment = null
        update(Phase.WAITING)
        replies.request(id)
        deadline.after(8_000) {
            if (turn == id && nextSegment == 1) stop(ReplyTimeout.FIRST_SEGMENT)
        }
        deadline.after(45_000) {
            if (turn == id) stop(ReplyTimeout.INCOMPLETE_REPLY)
        }
    }

    private fun advance() {
        if (operation != null || turn == null) return
        val segment = pending.removeFirstOrNull()
        if (segment != null) {
            val id = ++nextOperation
            operation = id
            playing = true
            update(Phase.PLAYING)
            audio.play(id, segment.samples)
        } else if (finalSegment != null) {
            turn = null
            if (game) completed++
            if (game && completed == 3) {
                game = false
                update(Phase.IDLE)
            } else openCapture()
        } else {
            val id = turn
            val expected = nextSegment
            update(Phase.WAITING)
            deadline.after(4_000) {
                if (turn == id && nextSegment == expected && finalSegment == null &&
                    phase == Phase.WAITING
                ) stop(ReplyTimeout.INCOMPLETE_REPLY)
            }
        }
    }

    private fun update(next: Phase) {
        phase = next
        changed(next, completed)
    }
}
