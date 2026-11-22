package com.littlebuddy

import android.annotation.SuppressLint
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.os.Build
import android.os.Handler
import android.os.SystemClock
import com.littlebuddy.voice.AudioPort
import com.littlebuddy.voice.PcmStream

internal class AndroidAudio(
    private val dispatcher: Handler,
    private val frame: (Long, Boolean, Boolean) -> Unit,
    failed: (Long) -> Unit,
    played: (Long) -> Unit,
    released: (Long) -> Unit,
    private val diagnostics: ((Int, String) -> Unit)?,
    private val pcm: ((Long, ShortArray, Int) -> Unit)? = null,
    private val captureStarted: ((Long) -> Unit)? = null,
    private val speechDetected: ((Long) -> Unit)? = null,
    startupBufferMs: Int = 120,
) : AudioPort {
    private val startupFrames = PLAY_RATE * startupBufferMs.also { require(it in 40..300) } / 1000
    private val worker = AudioWorker({ action -> dispatcher.post { action() } }, failed, played, released)

    override fun capture(operation: Long) = worker.submit(operation, ::record)

    override fun play(operation: Long, samples: ShortArray) =
        worker.submit(operation) { playTone(it, samples) }

    override fun playStream(operation: Long, stream: PcmStream) =
        worker.submit(operation) { playPcm(it, stream) }

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
            captureStarted?.invoke(operation.id)
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
                if (detector.detectedSpeechInRead && !operation.cancelled) speechDetected?.invoke(operation.id)
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
            while (!operation.cancelled) {
                val position = track.playbackHeadPosition
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

    private fun playPcm(operation: AudioWorker.Operation, stream: PcmStream) {
        val minimum = AudioTrack.getMinBufferSize(PLAY_RATE, AudioFormat.CHANNEL_OUT_MONO, PCM)
        check(minimum > 0)
        val track = AudioTrack.Builder()
            .setAudioAttributes(AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                .build())
            .setAudioFormat(AudioFormat.Builder().setSampleRate(PLAY_RATE)
                .setEncoding(PCM).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
            .setBufferSizeInBytes(maxOf(minimum, startupFrames * Short.SIZE_BYTES))
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()
        try {
            check(track.state == AudioTrack.STATE_INITIALIZED)
            val threshold = if (Build.VERSION.SDK_INT >= 31) {
                track.setStartThresholdInFrames(minOf(startupFrames, track.bufferSizeInFrames))
            } else track.bufferSizeInFrames
            // Bound the native queue even if a device reports an unusual minimum.
            check(threshold in 1..PLAY_RATE && track.bufferSizeInFrames in 1..PLAY_RATE)

            pumpPcm(operation, stream, threshold, object : PcmOutput {
                override val head get() = track.playbackHeadPosition
                override fun write(samples: ShortArray, offset: Int) =
                    track.write(samples, offset, samples.size - offset, AudioTrack.WRITE_NON_BLOCKING)
                override fun start() = track.play()
            }, SystemClock::elapsedRealtime) { Thread.sleep(5) }
        } finally {
            try {
                if (track.playState == AudioTrack.PLAYSTATE_PLAYING) track.pause()
                track.flush()
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
