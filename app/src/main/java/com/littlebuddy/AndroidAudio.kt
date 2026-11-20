package com.littlebuddy

import android.annotation.SuppressLint
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.os.Handler
import com.littlebuddy.voice.AudioPort

internal class AndroidAudio(
    private val dispatcher: Handler,
    private val frame: (Long, Boolean, Boolean) -> Unit,
    failed: (Long) -> Unit,
    played: (Long) -> Unit,
    released: (Long) -> Unit,
) : AudioPort {
    private val worker = AudioWorker({ action -> dispatcher.post { action() } }, failed, played, released)

    override fun capture(operation: Long) = worker.submit(operation, ::record)

    override fun play(operation: Long, samples: ShortArray) =
        worker.submit(operation) { playTone(it, samples) }

    override fun stop(operation: Long) = worker.stop(operation)

    fun close() = worker.close()

    @SuppressLint("MissingPermission")
    private fun record(operation: AudioWorker.Operation) {
        val minimum = AudioRecord.getMinBufferSize(MIC_RATE, AudioFormat.CHANNEL_IN_MONO, PCM)
        check(minimum > 0)
        val recorder = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION, MIC_RATE, AudioFormat.CHANNEL_IN_MONO, PCM,
            maxOf(minimum, MIC_RATE / 5 * Short.SIZE_BYTES),
        )
        val samples = ShortArray(MIC_RATE / 50)
        try {
            check(recorder.state == AudioRecord.STATE_INITIALIZED)
            if (!operation.commitStart()) return
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
                        if (!worker.closed && !operation.cancelled) frame(operation.id, speech, endpoint)
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

    private fun playTone(operation: AudioWorker.Operation, samples: ShortArray) {
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
            if (operation.cancelled) return
            check(track.write(samples, 0, samples.size) == samples.size)
            if (!operation.commitStart()) return
            track.play()
            while (!operation.cancelled && track.playbackHeadPosition < samples.size) {
                Thread.sleep(10)
            }
        } finally {
            try {
                if (track.playState == AudioTrack.PLAYSTATE_PLAYING) track.stop()
            } finally {
                track.release()
            }
        }
    }

    private companion object {
        const val PCM = AudioFormat.ENCODING_PCM_16BIT
        const val MIC_RATE = 16_000
        const val PLAY_RATE = 24_000
    }
}
