package com.littlebuddy

import kotlin.math.roundToInt
import kotlin.math.sqrt

/** Energy-based endpoint detector for 20 ms mono PCM16 windows. */
internal class SpeechDetector(private val windowSamples: Int) {
    enum class Event { NONE, SPEECH, END }

    private var filled = 0
    private var sum = 0L
    private var squares = 0L
    private var calibrationWindows = 0
    private var floor = Double.POSITIVE_INFINITY
    private var voicedWindows = 0
    private var quietWindows = 0
    private var heardSpeech = false
    var energy = 0
        private set
    var decision = "校准"
        private set

    // Each read is at most one window, so it can complete at most one window.
    fun accept(samples: ShortArray, count: Int): Event {
        var event = Event.NONE
        for (index in 0 until count) {
            val sample = samples[index].toLong()
            sum += sample
            squares += sample * sample
            if (++filled == windowSamples) {
                val mean = sum.toDouble() / filled
                val rms = sqrt((squares.toDouble() / filled - mean * mean).coerceAtLeast(0.0))
                event = classify(rms)
                filled = 0
                sum = 0
                squares = 0
            }
        }
        return event
    }

    private fun classify(rms: Double): Event {
        energy = rms.roundToInt()
        if (calibrationWindows < 8) {
            floor = minOf(floor, rms)
            calibrationWindows++
            return Event.NONE
        }

        // After a confirmed onset, allow quieter speech to keep the round open.
        val voiced = if (heardSpeech) rms >= maxOf(60.0, floor * 1.6)
            else rms >= maxOf(90.0, floor * 2.5)
        decision = if (voiced) "语音候选" else "低于门限"
        if (!voiced && !heardSpeech) floor += (rms - floor) * 0.05
        voicedWindows = if (voiced) voicedWindows + 1 else 0
        if (voicedWindows == 4) {
            if (!heardSpeech) {
                heardSpeech = true
                decision = "有效语音"
                return Event.SPEECH
            }
        }
        if (heardSpeech) {
            // Brief spikes during a pause must not postpone endpoint detection.
            if (voicedWindows >= 4) decision = "有效语音"
            quietWindows = if (voicedWindows >= 4) 0 else quietWindows + 1
            // Give a candidate that starts near the deadline time to confirm.
            if (quietWindows >= 75 && voicedWindows == 0) return Event.END
        }
        return Event.NONE
    }
}
