package com.littlebuddy

import android.annotation.SuppressLint
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.os.Handler
import android.os.SystemClock
import android.util.Log
import com.littlebuddy.voice.AudioPort

internal class AndroidAudio(
    private val dispatcher: Handler,
    private val frame: (Long, Boolean, Boolean) -> Unit,
    failed: (Long) -> Unit,
    played: (Long) -> Unit,
    released: (Long) -> Unit,
    private val diagnostics: ((Int, String) -> Unit)?,
    private val pcm: ((Long, ShortArray, Int) -> Unit)? = null,
    private val tracePlayback: Boolean = false,
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
            var nextDiagnostic = 0L
            val detector = SpeechDetector(samples.size)
            while (!operation.cancelled) {
                val count = recorder.read(samples, 0, samples.size, AudioRecord.READ_NON_BLOCKING)
                check(count >= 0)
                if (count == 0) {
                    Thread.sleep(10)
                    continue
                }
                pcm?.invoke(operation.id, samples, count)
                val event = detector.accept(samples, count)
                val speech = event == SpeechDetector.Event.SPEECH
                val endpoint = event == SpeechDetector.Event.END
                val now = if (diagnostics != null) SystemClock.elapsedRealtime() else 0L
                val showDiagnostics = diagnostics != null && (now >= nextDiagnostic || speech || endpoint)
                if (showDiagnostics) nextDiagnostic = now + 200
                if (opening || speech || endpoint || showDiagnostics) {
                    val energy = detector.energy
                    val decision = detector.decision
                    dispatcher.post {
                        if (!worker.closed && !operation.cancelled) {
                            if (showDiagnostics) diagnostics?.invoke(energy, decision)
                            frame(operation.id, speech, endpoint)
                        }
                    }
                }
                opening = false
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
            var reportHead = tracePlayback
            while (!operation.cancelled) {
                val position = track.playbackHeadPosition
                if (reportHead && position > 0) {
                    Log.d("LittleBuddyVoice", "playback_head t_ms=${SystemClock.elapsedRealtime()} op=${operation.id}")
                    reportHead = false
                }
                if (position >= samples.size) break
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
