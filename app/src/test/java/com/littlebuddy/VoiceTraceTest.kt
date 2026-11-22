package com.littlebuddy

import org.junit.Assert.*
import org.junit.Test

class VoiceTraceTest {
    @Test fun timingIsOncePerEventAndOnlyFirstSegmentCarriesTurnLatency() {
        var now = 100L
        val events = mutableListOf<String>()
        val trace = VoiceTrace(5, { now }, events::add)
        trace.started()
        now = 110
        trace.speechDetected()
        now = 120
        trace.speechDetected()
        now = 150
        trace.endpointConfirmed()
        now = 160
        trace.endpointConfirmed()
        trace.pcm(1)
        trace.pcm(1)
        trace.playback("playback_requested", 6, 1)
        now = 180
        trace.playback("playback_head_first_advance", 99, 1)
        trace.playback("playback_head_first_advance", 6, 1)
        trace.playback("playback_head_first_advance", 6, 1)
        trace.pcm(2)
        trace.playback("playback_requested", 7, 2)
        trace.playback("playback_head_first_advance", 7, 2)
        trace.finish(true)
        trace.finish(false)
        trace.pcm(3)
        trace.playback("playback_requested", 8, 3)

        assertEquals(10, events.size)
        assertEquals(1, events.map { it.substringAfter("turn_id=").substringBefore(' ') }.distinct().size)
        assertTrue(events[1].startsWith("last_speech_detected t_ms=120 "))
        assertTrue(events[2].startsWith("endpoint_confirmed t_ms=150 "))
        assertTrue(events[3].endsWith("op_id=5 segment=1 endpoint_to_first_pcm_ms=10"))
        assertTrue(events[5].endsWith("op_id=6 segment=1 pcm_to_head_ms=20 endpoint_to_first_head_ms=30 estimated_last_speech_to_first_head_ms=60"))
        assertTrue(events[8].endsWith("op_id=7 segment=2 pcm_to_head_ms=0"))
        assertTrue(events[9].startsWith("turn_finished "))
    }

    @Test fun cancelledAttemptCannotEmitOrReuseTheNextTurnId() {
        val events = mutableListOf<String>()
        val old = VoiceTrace(1, { 0L }, events::add)
        val current = VoiceTrace(2, { 1L }, events::add)
        old.started()
        old.finish(false)
        current.started()
        old.endpointConfirmed()
        old.pcm(1)
        current.endpointConfirmed()
        assertEquals(4, events.size)
        assertEquals(2, events.map { it.substringAfter("turn_id=").substringBefore(' ') }.distinct().size)
        assertTrue(events.last().endsWith("op_id=2 segment=0"))
    }
}
