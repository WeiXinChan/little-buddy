package com.littlebuddy

import java.util.UUID

internal class VoiceTrace(
    private val capture: Long,
    private val now: () -> Long,
    private val sink: (String) -> Unit,
) {
    val id: String = UUID.randomUUID().toString()
    private var closed = false
    private var recordingStarted = false
    private var endpoint: Long? = null
    private var speech: Long? = null
    private val firstPcm = mutableMapOf<Int, Long>()
    private val requested = mutableMapOf<Int, Long>()
    private val head = mutableSetOf<Int>()

    @Synchronized fun started() {
        if (closed || recordingStarted) return
        recordingStarted = true
        emit("capture_started", capture, now())
    }

    @Synchronized fun speechDetected() {
        if (!closed && endpoint == null) speech = now()
    }

    @Synchronized fun endpointConfirmed() {
        if (closed || !recordingStarted || endpoint != null) return
        speech?.let { emit("last_speech_detected", capture, it) }
        val time = now()
        endpoint = time
        emit("endpoint_confirmed", capture, time)
    }

    @Synchronized fun pcm(segment: Int) {
        if (closed || segment in firstPcm) return
        val time = now()
        firstPcm[segment] = time
        emit("first_pcm_received", capture, time, segment,
            if (segment == 1) elapsed("endpoint_to_first_pcm_ms", endpoint, time) else "")
    }

    @Synchronized fun playback(event: String, op: Long, segment: Int) {
        if (closed || segment !in firstPcm) return
        val time = now()
        val metrics = when (event) {
            "playback_requested" -> {
                if (requested.putIfAbsent(segment, op) != null) return
                ""
            }
            "playback_head_first_advance" -> {
                if (requested[segment] != op || !head.add(segment)) return
                elapsed("pcm_to_head_ms", firstPcm[segment], time) +
                    if (segment == 1) elapsed("endpoint_to_first_head_ms", endpoint, time) +
                        elapsed("estimated_last_speech_to_first_head_ms", speech, time) else ""
            }
            else -> return
        }
        emit(event, op, time, segment, metrics)
    }

    @Synchronized fun finish(success: Boolean, code: VoiceFailure? = null) {
        val metrics = code?.let { " error_code=${it.name.lowercase()}" } ?: ""
        emit(if (success) "turn_finished" else "turn_cancelled", capture, now(), metrics = metrics)
        closed = true
    }

    private fun elapsed(name: String, start: Long?, end: Long) =
        if (start == null) "" else " $name=${end - start}"

    private fun emit(event: String, op: Long, time: Long, segment: Int = 0, metrics: String = "") {
        if (!closed) sink("$event t_ms=$time turn_id=$id op_id=$op segment=$segment$metrics")
    }
}
