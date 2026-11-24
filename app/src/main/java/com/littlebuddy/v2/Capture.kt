package com.littlebuddy.v2

import android.annotation.SuppressLint
import android.content.res.AssetManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.os.Handler
import com.littlebuddy.SherpaWake
import com.littlebuddy.SpeechDetector
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

internal enum class CapturePhase { NOT_STARTED, THREAD_START, AUDIO_RECORD, WAKE_KWS, MANAGEMENT_KWS, START, READ, RELEASE, RELEASED, QUARANTINED }

/** One recorder throughout wake/continuation and full-duplex interaction.
 * No idle upload. Finite pre-roll preserves the KWS tail and short input onset.
 */
internal class Capture(private val assets: AssetManager, private val owner: Handler,
                       private val client: VoiceClient, private val failed: () -> Unit,
                       private val managementChanged: (Boolean) -> Unit = {}) {
    private val commandGeneration = AtomicLong(0)
    @Volatile private var management = false
    fun enterManagement() { commandGeneration.incrementAndGet(); management = true }
    fun exitManagement() { commandGeneration.incrementAndGet(); management = false }
    @Volatile var phase = CapturePhase.NOT_STARTED; private set
    @Volatile var failedPhase: CapturePhase? = null; private set
    private val cancelled = AtomicBoolean(false)
    private val pending = AtomicInteger(0)
    private var thread: Thread? = null
    @Volatile var nativeProof = RecorderProof(); private set
    var quarantined = false; private set
    fun start() {
        check(thread == null && !quarantined)
        cancelled.set(false)
        phase = CapturePhase.THREAD_START
        thread = Thread({ record() }, "v2-capture").apply { start() }
    }
    @SuppressLint("MissingPermission")
    private fun record() {
        var recorder: AudioRecord? = null
        var aec: AcousticEchoCanceler? = null
        var wake: SherpaWake? = null
        var commands: SherpaWake? = null
        val buffered = WakeSamples()
        val frame = ShortArray(320)
        var position = 0L
        var firstAfterWake = false
        var awake = false
        var voiced = false
        var wakeBase = 0L
        var lastSpeech = 0L
        var sealed = 0L
        var idle = 0L
        var detector = SpeechDetector(320, initialFloor = 36.0)
        var uploadSamples = 0
        fun upload(data: ShortArray, speech: Boolean) {
            val ticket = commandGeneration.get()
            val capturedAt = android.os.SystemClock.elapsedRealtime()
            if (uploadSamples + data.size > 320000) error("input bound")
            uploadSamples += data.size
            check(pending.incrementAndGet() <= 20)
            owner.post {
                try { if (!cancelled.get() && !management && ticket == commandGeneration.get()) client.frame(data, speech, capturedAt) }
                finally { data.fill(0); pending.decrementAndGet() }
            }
        }
        try {
            phase = CapturePhase.AUDIO_RECORD
            val minimum = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO,
                                                       AudioFormat.ENCODING_PCM_16BIT)
            check(minimum in 1..32000)
            val native = AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION, 16000,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(minimum, 6400))
            recorder = native
            check(native.state == AudioRecord.STATE_INITIALIZED)
            if (AcousticEchoCanceler.isAvailable()) {
                aec = AcousticEchoCanceler.create(native.audioSessionId)
                aec?.enabled = true // Availability/enabled are diagnostics, not acoustic PASS.
            }
            phase = CapturePhase.WAKE_KWS
            wake = SherpaWake(assets)
            phase = CapturePhase.MANAGEMENT_KWS
            commands = SherpaWake(assets, "*", "wake/manage.txt")
            if (cancelled.get()) return
            phase = CapturePhase.START
            native.startRecording()
            check(native.recordingState == AudioRecord.RECORDSTATE_RECORDING)
            nativeProof = RecorderProof(native.audioSessionId, started=true, recording=true)
            phase = CapturePhase.READ
            while (!cancelled.get()) {
                val count = native.read(frame, 0, frame.size, AudioRecord.READ_NON_BLOCKING)
                check(count >= 0)
                if (count == 0) { Thread.sleep(5); continue }
                check(native.recordingState == AudioRecord.RECORDSTATE_RECORDING)
                nativeProof = nativeProof.copy(recording=true, frames=nativeProof.frames+count)
                if (commands?.accept(frame, count) != null) {
                    val command = commands?.detectedKeyword
                    commands?.close(); commands = SherpaWake(assets, "*", "wake/manage.txt")
                    val entering = !management && command == "进入管理"
                    val exiting = management && command in listOf("取消", "退出管理")
                    if (entering || exiting) {
                        commandGeneration.incrementAndGet()
                        management = entering
                        buffered.clear(); awake = false; voiced = false; uploadSamples = 0
                        wake?.close(); wake = SherpaWake(assets); wakeBase = buffered.position
                        owner.post { if (!cancelled.get()) {
                            client.management(entering); managementChanged(entering)
                        } }
                        continue
                    }
                }
                if (management) { frame.fill(0); continue }
                buffered.push(frame, count)
                position = buffered.position
                if (idle != client.idleSerial) {
                    idle = client.idleSerial
                    buffered.clear()
                    awake = false; voiced = false; uploadSamples = 0
                    detector = SpeechDetector(320, initialFloor = 36.0); wakeBase = position
                    wake?.close(); wake = SherpaWake(assets)
                }
                if (!awake) {
                    val tail = wake?.accept(frame, count) ?: continue
                    if (!client.connectionActive) {
                        // Unconfigured local KWS never builds/uploads child expressions.
                        owner.post { if (!cancelled.get()) client.wake() }
                        wake?.close(); wake = SherpaWake(assets)
                        wakeBase = position; buffered.clear()
                        continue
                    }
                    awake = true
                    wake?.close(); wake = null
                    detector = SpeechDetector(320, initialFloor = 36.0)
                    val wakeBoundary = (android.os.SystemClock.elapsedRealtime() -
                        ((position - (wakeBase + tail).coerceIn(0, position)) * 1000 / 16000)).coerceAtLeast(0)
                    owner.post { if (!cancelled.get()) client.wake(wakeBoundary) }
                    // Absolute ring and KWS-local coordinates share a recorded origin.
                    lastSpeech = android.os.SystemClock.elapsedRealtime()
                    val absoluteTail = (wakeBase + tail).coerceIn(0, position)
                    buffered.begin(absoluteTail)
                    firstAfterWake = true
                    var continuation = false
                    // KWS can report after the first intent samples have arrived.
                    // Feed the cached tail to the real VAD, without consuming the
                    // upload cursor or waiting for a future recorder frame.
                    buffered.inspectAfter(absoluteTail) { cached ->
                        detector.accept(cached, cached.size)
                        continuation = continuation || detector.detectedSpeechInRead
                        cached.fill(0)
                    }
                    if (continuation) {
                        voiced = true; firstAfterWake = false
                        buffered.read().forEach { upload(it, true) }
                    }
                    continue
                }
                if (sealed != client.inputSerial) { uploadSamples = 0; sealed = client.inputSerial }
                detector.accept(frame, count) // V1 END is deliberately not a V2 endpoint.
                val speech = detector.detectedSpeechInRead
                val now = android.os.SystemClock.elapsedRealtime()
                if (speech) {
                    lastSpeech = now
                    if (!voiced) {
                        voiced = true
                        buffered.onset()
                        firstAfterWake = false
                        buffered.read().forEach { upload(it, true) }
                    } else buffered.read().forEach { upload(it, true) }
                } else if (voiced && now - lastSpeech <= 300) {
                    buffered.read().forEach { upload(it, false) }
                } else {
                    owner.post { if (!cancelled.get()) client.quiet() }
                    if (voiced) { voiced = false; detector = SpeechDetector(320, initialFloor = 36.0) }
                    if (!firstAfterWake) buffered.follow()
                }
                // Per-expression audio is bounded. Endpoint completion resets it via
                // the owner callback; the backend separately retains the 600s session.
                if (uploadSamples >= 300000) error("input capacity")
            }
        } catch (_: Exception) {
            failedPhase = phase
            if (!cancelled.get()) owner.post { failed() }
        } finally {
            phase = CapturePhase.RELEASE
            frame.fill(0); buffered.clear()
            try { commands?.close(); wake?.close() } catch (_: Exception) { quarantined = true }
            try { aec?.release() } catch (_: Exception) { quarantined = true }
            try {
                if (recorder?.recordingState == AudioRecord.RECORDSTATE_RECORDING) recorder?.stop()
                check(recorder?.recordingState == AudioRecord.RECORDSTATE_STOPPED)
                nativeProof = nativeProof.copy(recording=false, stopped=true)
            } catch (_: Exception) { quarantined = true }
            try {
                recorder?.release()
                check(recorder?.state == AudioRecord.STATE_UNINITIALIZED)
                nativeProof = nativeProof.copy(recording=false, released=true)
            } catch (_: Exception) { quarantined = true }
            phase = if (quarantined) CapturePhase.QUARANTINED else CapturePhase.RELEASED
            if (!cancelled.get()) owner.post { failed() }
        }
    }
    fun close() {
        cancelled.set(true)
        val old = thread ?: return
        old.join(500)
        if (old.isAlive) quarantined = true
        // Never permit another recorder when the original has no release confirmation.
        if (!old.isAlive) thread = null
    }
}
