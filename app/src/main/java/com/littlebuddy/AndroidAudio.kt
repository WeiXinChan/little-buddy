package com.littlebuddy

import android.annotation.SuppressLint
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.os.Handler
import com.littlebuddy.voice.AudioPort
import java.util.concurrent.Executors

internal class AndroidAudio(
    private val dispatcher: Handler,
    private val frame: (Long, Boolean, Boolean) -> Unit,
    private val failed: (Long) -> Unit,
    private val played: (Long) -> Unit,
    private val released: (Long) -> Unit,
) : AudioPort {
    private class Operation(val id: Long) {
        @Volatile var cancelled = false
        var track: AudioTrack? = null
    }

    private val worker = Executors.newSingleThreadExecutor()
    private var active: Operation? = null
    private var closed = false

    override fun capture(operation: Long) = submit(operation, ::record)

    override fun play(operation: Long, samples: ShortArray) =
        submit(operation) { playTone(it, samples) }

    override fun stop(operation: Long) {
        val current = active ?: return
        if (current.id != operation) return
        synchronized(current) {
            current.cancelled = true
            current.track?.let { track -> runCatching { track.setVolume(0f) } }
        }
    }

    fun close() {
        closed = true
        active?.let { stop(it.id) }
        worker.shutdown()
    }

    private fun submit(id: Long, task: (Operation) -> Unit) {
        check(active == null && !closed)
        val current = Operation(id)
        active = current
        worker.execute {
            val success = try {
                if (!current.cancelled) task(current)
                true
            } catch (_: RuntimeException) {
                false
            }
            dispatcher.post {
                if (!closed) {
                    if (!current.cancelled) {
                        if (success) played(id) else failed(id)
                    }
                    active = null
                    released(id)
                }
            }
        }
    }

    @SuppressLint("MissingPermission")
    private fun record(operation: Operation) {
        val minimum = AudioRecord.getMinBufferSize(MIC_RATE, AudioFormat.CHANNEL_IN_MONO, PCM)
        check(minimum > 0)
        val recorder = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION, MIC_RATE, AudioFormat.CHANNEL_IN_MONO, PCM,
            maxOf(minimum, MIC_RATE / 5 * Short.SIZE_BYTES),
        )
        val samples = ShortArray(MIC_RATE / 50)
        try {
            check(recorder.state == AudioRecord.STATE_INITIALIZED)
            if (operation.cancelled) return
            recorder.startRecording()
            check(recorder.recordingState == AudioRecord.RECORDSTATE_RECORDING)
            var opening = true
            var heardSpeech = false
            var silentSamples = 0
            while (!operation.cancelled) {
                val count = recorder.read(samples, 0, samples.size, AudioRecord.READ_NON_BLOCKING)
                check(count >= 0)
                if (count == 0) {
                    Thread.sleep(10)
                    continue
                }
                var power = 0L
                for (i in 0 until count) power += samples[i].toLong() * samples[i]
                // Fixed RMS gate for this local simulation. Device behavior needs calibration.
                val speech = power >= 600L * 600 * count
                silentSamples = if (speech) 0 else silentSamples + count
                val endpoint = heardSpeech && silentSamples >= MIC_RATE * 9 / 10
                if (opening || (speech && !heardSpeech) || endpoint) {
                    dispatcher.post {
                        if (!closed && !operation.cancelled) frame(operation.id, speech, endpoint)
                    }
                }
                opening = false
                heardSpeech = heardSpeech || speech
                if (endpoint) {
                    // Keep ownership until the dispatcher requests release.
                    while (!operation.cancelled) Thread.sleep(10)
                }
            }
        } finally {
            samples.fill(0)
            try {
                if (recorder.recordingState == AudioRecord.RECORDSTATE_RECORDING) recorder.stop()
            } finally {
                recorder.release()
            }
        }
    }

    private fun playTone(operation: Operation, samples: ShortArray) {
        val track = AudioTrack.Builder()
            .setAudioAttributes(AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build())
            .setAudioFormat(AudioFormat.Builder()
                .setSampleRate(PLAY_RATE)
                .setEncoding(PCM)
                .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                .build())
            .setBufferSizeInBytes(samples.size * Short.SIZE_BYTES)
            .setTransferMode(AudioTrack.MODE_STATIC)
            .build()
        try {
            check(track.write(samples, 0, samples.size) == samples.size)
            synchronized(operation) {
                if (operation.cancelled) return
                operation.track = track
                track.play()
            }
            while (!operation.cancelled && track.playbackHeadPosition < samples.size) {
                Thread.sleep(10)
            }
        } finally {
            synchronized(operation) {
                operation.track = null
                try {
                    if (track.playState == AudioTrack.PLAYSTATE_PLAYING) track.stop()
                } finally {
                    track.release()
                }
            }
        }
    }

    private companion object {
        const val PCM = AudioFormat.ENCODING_PCM_16BIT
        const val MIC_RATE = 16_000
        const val PLAY_RATE = 24_000
    }
}
