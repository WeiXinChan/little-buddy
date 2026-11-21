package com.littlebuddy

import com.littlebuddy.SpeechDetector.Event
import org.junit.Assert.assertEquals
import org.junit.Test

class SpeechDetectorTest {
    private val detector = SpeechDetector(320)

    private fun feed(windows: Int, level: Int): List<Event> {
        val samples = ShortArray(160) { (if (it % 2 == 0) level else -level).toShort() }
        return List(windows) {
            assertEquals(Event.NONE, detector.accept(samples, samples.size))
            detector.accept(samples, samples.size)
        }.filter { it != Event.NONE }
    }

    @Test fun quieterSpeechContinuesAfterOnsetAndEndsAfterTailSilence() {
        assertEquals(emptyList<Event>(), feed(50, 35))
        assertEquals(listOf(Event.SPEECH), feed(4, 140))
        assertEquals(emptyList<Event>(), feed(100, 75))
        assertEquals(emptyList<Event>(), feed(74, 35))
        assertEquals(listOf(Event.END), feed(1, 35))
    }

    @Test fun shortPauseThenResumedSpeechResetsTail() {
        feed(8, 35)
        feed(4, 140)
        assertEquals(emptyList<Event>(), feed(60, 35))
        assertEquals(emptyList<Event>(), feed(4, 75))
        assertEquals(emptyList<Event>(), feed(74, 35))
        assertEquals(listOf(Event.END), feed(1, 35))
    }

    @Test fun speechResumingJustBeforeTailDeadlineCanConfirm() {
        feed(8, 35)
        feed(4, 140)
        assertEquals(emptyList<Event>(), feed(74, 35))
        assertEquals(emptyList<Event>(), feed(4, 75))
        assertEquals(emptyList<Event>(), feed(74, 35))
        assertEquals(listOf(Event.END), feed(1, 35))
    }

    @Test fun pulseAtDeadlineDelaysEndOnlyUntilItStops() {
        feed(8, 35)
        feed(4, 140)
        feed(74, 35)
        assertEquals(emptyList<Event>(), feed(3, 1_000))
        assertEquals(listOf(Event.END), feed(1, 35))
    }

    @Test fun steadyBackgroundAndShortPulseDoNotStartSpeech() {
        assertEquals(emptyList<Event>(), feed(100, 180))
        assertEquals(emptyList<Event>(), feed(3, 1_000))
        assertEquals(emptyList<Event>(), feed(100, 180))
    }

    @Test fun pulseDuringTailDoesNotResetIt() {
        feed(8, 35)
        feed(4, 140)
        feed(60, 35)
        assertEquals(emptyList<Event>(), feed(3, 1_000))
        assertEquals(emptyList<Event>(), feed(11, 35))
        assertEquals(listOf(Event.END), feed(1, 35))
    }
}
