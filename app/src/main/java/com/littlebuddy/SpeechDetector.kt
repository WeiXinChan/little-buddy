package com.littlebuddy

import kotlin.math.roundToInt
import kotlin.math.sqrt

/** Energy-based endpoint detector for 20 ms mono PCM16 windows. */
internal class SpeechDetector(private val windowSamples: Int) {
    enum class Event { NONE, SPEECH, END }

    private val sliceSamples = windowSamples / 4
    private val sliceEnergy = DoubleArray(4)
    private var filled = 0
    private var sum = 0L
    private var squares = 0L
    private var sliceSum = 0L
    private var sliceSquares = 0L
    private var calibrationWindows = 0
    private var floor = Double.POSITIVE_INFINITY
    private var voicedWindows = 0
    private var onsetRms = 0.0
    private var previousRms = 0.0
    private var falling = false
    private var reverberating = false
    private var quietWindows = 0
    private var heardSpeech = false
    var detectedSpeechInRead = false
        private set
    var energy = 0
        private set
    var decision = "校准"
        private set

    init {
        require(windowSamples > 0 && windowSamples % sliceEnergy.size == 0)
    }

    // Each read is at most one window, so it can complete at most one window.
    fun accept(samples: ShortArray, count: Int): Event {
        detectedSpeechInRead = false
        var event = Event.NONE
        for (index in 0 until count) {
            val sample = samples[index].toLong()
            val power = sample * sample
            sum += sample
            squares += power
            sliceSum += sample
            sliceSquares += power
            filled++
            if (filled % sliceSamples == 0) {
                sliceEnergy[filled / sliceSamples - 1] = rms(sliceSum, sliceSquares, sliceSamples)
                sliceSum = 0
                sliceSquares = 0
            }
            if (filled == windowSamples) {
                event = classify(rms(sum, squares, filled))
                filled = 0
                sum = 0
                squares = 0
            }
        }
        return event
    }

    private fun rms(sum: Long, squares: Long, count: Int): Double {
        val mean = sum.toDouble() / count
        return sqrt((squares.toDouble() / count - mean * mean).coerceAtLeast(0.0))
    }

    private fun classify(rms: Double): Event {
        energy = rms.roundToInt()
        if (calibrationWindows < 8) {
            floor = minOf(floor, rms)
            calibrationWindows++
            return Event.NONE
        }

        val threshold = if (heardSpeech) maxOf(60.0, floor * 1.6)
            else maxOf(90.0, floor * 2.5)
        val aboveThreshold = rms >= threshold
        // A loud edge can raise the window RMS without filling most of that window.
        val sustained = aboveThreshold && sliceEnergy.count { it >= threshold } >= 3
        if (!aboveThreshold && !heardSpeech) floor += (rms - floor) * 0.05
        updateCandidate(sustained, rms)
        decision = when {
            voicedWindows >= 4 -> "有效语音"
            voicedWindows > 0 -> "语音候选"
            aboveThreshold -> "疑似瞬态"
            else -> "低于门限"
        }

        detectedSpeechInRead = voicedWindows >= 4
        if (!heardSpeech && voicedWindows >= 4) {
            heardSpeech = true
            return Event.SPEECH
        }
        if (heardSpeech) {
            quietWindows = if (voicedWindows >= 4) 0 else quietWindows + 1
            // Give a candidate that starts near the deadline time to confirm.
            if (quietWindows >= 75 && voicedWindows == 0) return Event.END
        }
        return Event.NONE
    }

    private fun updateCandidate(sustained: Boolean, rms: Double) {
        if (!sustained || (reverberating && rms > previousRms * 1.25)) {
            reverberating = false
        }
        if (!sustained || reverberating) {
            voicedWindows = 0
        } else {
            if (voicedWindows == 0) {
                onsetRms = rms
                falling = true
            } else {
                falling = falling && rms <= previousRms
            }
            voicedWindows++
            // Reject a steep, uninterrupted decay and ignore its remaining tail
            // until the envelope recovers or falls below the window criterion.
            if (voicedWindows == 4 && falling && rms <= onsetRms / 4) {
                voicedWindows = 0
                reverberating = true
            }
        }
        previousRms = rms
    }
}
