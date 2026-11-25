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

/** One recorder throughout wake/continuation and full-duplex interaction.
 * No idle upload. Finite pre-roll preserves the KWS tail and short input onset.
 */
internal class Capture(private val assets: AssetManager, private val owner: Handler,
                       private val client: VoiceClient, private val allowed: () -> Boolean = { true },
                       private val recording: (Boolean)->Unit = {}, private val failed: () -> Unit) {
    private val started=AtomicBoolean(false)
    private val cancelled = AtomicBoolean(false)
    @Volatile private var lease:RecorderLease?=null
    private val nativeLock=Any()
    @Volatile private var nativeHandle:AudioRecord?=null
    private val stopRequested=AtomicBoolean(false)
    private val uploads=CaptureUploads({owner.post(it)},android.os.SystemClock::elapsedRealtime,
        { !cancelled.get() && allowed() },{data,speech,at->client.frame(data,speech,at)},
        {requestCancel();owner.post{failed()}})
    @Volatile private var thread: Thread? = null
    @Volatile var nativeProof = RecorderProof(); private set
    @Volatile var quarantined = false; private set
    fun start() {
        check(started.compareAndSet(false,true) && thread == null && !quarantined)
        lease=ProcessRecorders.acquire("child")
        if(lease==null){quarantined=true;owner.post{if(allowed())failed()};return}
        val hold=checkNotNull(lease)
        val worker=Thread({ record() }, "v2-capture");thread=worker
        try {
            worker.start()
            Thread({worker.join();hold.workerFinished()},"v2-capture-join").start()
        } catch(_:Exception){quarantined=true;requestCancel()}
    }
    @SuppressLint("MissingPermission")
    private fun record() {
        var recorder: AudioRecord? = null
        var aec: AcousticEchoCanceler? = null
        var wake: SherpaWake? = null
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
        var lastCapturedAt=android.os.SystemClock.elapsedRealtime()
        var uploadSamples = 0
        fun upload(batch: List<ShortArray>, speech: Boolean) {
            val count=batch.sumOf{it.size}
            if(uploadSamples+count>320000){batch.forEach{it.fill(0)};error("input bound")}
            uploadSamples+=count
            check(uploads.offer(batch,speech,lastCapturedAt))
        }
        var attemptedNative=false
        var attemptedWake=false
        var modelUncertain=false
        try {
            val minimum = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO,
                                                       AudioFormat.ENCODING_PCM_16BIT)
            check(minimum in 1..32000)
            val nativeBytes=maxOf(minimum,6400)
            val nativeRoomMs=nativeBytes/32L
            uploads.nativeRoom(nativeBytes)
            if(cancelled.get() || !allowed())return
            attemptedNative=true
            val native = AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION, 16000,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, nativeBytes)
            recorder = native
            synchronized(nativeLock){nativeHandle=native}
            check(native.state == AudioRecord.STATE_INITIALIZED)
            if (AcousticEchoCanceler.isAvailable()) {
                aec = AcousticEchoCanceler.create(native.audioSessionId)
                aec?.enabled = true // Availability/enabled are diagnostics, not acoustic PASS.
            }
            attemptedWake=true
            wake = SherpaWake(assets){!cancelled.get() && allowed()}
            if (cancelled.get() || !allowed()) return
            synchronized(nativeLock){
                if(cancelled.get() || !allowed())return
                native.startRecording()
            }
            check(native.recordingState == AudioRecord.RECORDSTATE_RECORDING)
            nativeProof = RecorderProof(native.audioSessionId, started=true, recording=true)
            runCatching{recording(true)}
            var lastRead=android.os.SystemClock.elapsedRealtime()
            while (!cancelled.get() && allowed()) {
                check(uploads.awaitRoom(frame.size,maxOf(1L,nativeRoomMs-20))){"capture queue continuity"}
                val beforeRead=android.os.SystemClock.elapsedRealtime()
                check(beforeRead-lastRead in 0..nativeRoomMs){"native buffer continuity"}
                val count = native.read(frame, 0, frame.size, AudioRecord.READ_NON_BLOCKING)
                lastRead=android.os.SystemClock.elapsedRealtime()
                if(cancelled.get() || !allowed())break
                check(lastRead-beforeRead in 0..nativeRoomMs){"native read continuity"}
                check(count in 0..frame.size)
                if (count == 0) { Thread.sleep(5); continue }
                check(native.recordingState == AudioRecord.RECORDSTATE_RECORDING)
                nativeProof = nativeProof.copy(recording=true, frames=nativeProof.frames+count)
                lastCapturedAt=lastRead // never relabel cached PCM with a later KWS/upload timestamp
                buffered.push(frame, count)
                position = buffered.position
                if (awake && idle != client.idleSerial) {
                    idle = client.idleSerial
                    awake = false; voiced = false; uploadSamples = 0
                    detector = SpeechDetector(320, initialFloor = 36.0); wakeBase = wakeOrigin(position,count)
                    attemptedWake=true
                    wake = SherpaWake(assets){!cancelled.get() && allowed()}
                }
                if (!awake) {
                    if(cancelled.get() || !allowed())break
                    val tail = wake?.accept(frame, count) ?: continue
                    if(cancelled.get() || !allowed())break
                    awake = true
                    try {wake?.close()}catch(failure:Exception){modelUncertain=true;wake=null;throw failure}
                    wake = null
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
                        try {
                            if(!cancelled.get() && allowed()) {
                                detector.accept(cached,cached.size)
                                continuation=continuation || detector.detectedSpeechInRead
                            }
                        } finally {cached.fill(0)}
                    }
                    if (continuation) {
                        voiced = true; firstAfterWake = false
                        upload(buffered.read(), true)
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
                        upload(buffered.read(), true)
                    } else upload(buffered.read(), true)
                } else if (voiced && now - lastSpeech <= 300) {
                    upload(buffered.read(), false)
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
            if (!cancelled.get()) owner.post { if(!cancelled.get() && allowed())failed() }
        } finally {
            uploads.cancel();frame.fill(0);buffered.clear();runCatching{recording(false)}
            // Native stop/release precedes any potentially blocking model disposal.
            var released=!attemptedNative
            synchronized(nativeLock) {
                try {
                    recorder?.let { native ->
                        if(native.recordingState==AudioRecord.RECORDSTATE_RECORDING)native.stop()
                        check(native.recordingState==AudioRecord.RECORDSTATE_STOPPED)
                        nativeProof=nativeProof.copy(recording=false,stopped=true)
                    }
                } catch(_:Exception){quarantined=true}
                try {
                    recorder?.let { native ->
                        native.release();check(native.state==AudioRecord.STATE_UNINITIALIZED)
                        nativeProof=nativeProof.copy(recording=false,released=true);released=true
                    }
                } catch(_:Exception){quarantined=true}
                nativeHandle=null
            }
            if(released)lease?.nativeReleased()
            var disposed=!modelUncertain
            try { aec?.release() } catch(_:Exception){quarantined=true;disposed=false}
            // A blocked close retains the process lease even though native is already released.
            try { wake?.close() } catch(_:Exception){quarantined=true;return}
            if(disposed && (!attemptedWake || wake!=null || awake))lease?.modelsReleased()
            if(!cancelled.get())owner.post {if(!cancelled.get() && allowed())failed()}
        }
    }
    /** Caller-thread cancellation never waits for the audio owner. Native stop is independent;
     * the shared lease includes its completion and the original model worker's completion. */
    fun requestCancel() {
        cancelled.set(true);uploads.cancel()
        if(!stopRequested.compareAndSet(false,true))return
        val hold=lease ?: return
        if(!hold.beginStop())return
        Thread({try { synchronized(nativeLock) {
            nativeHandle?.let {if(it.recordingState==AudioRecord.RECORDSTATE_RECORDING)it.stop()}
        }}catch(_:Exception){quarantined=true}finally{hold.endStop()}},"v2-capture-stop").start()
    }
    fun close() {
        requestCancel()
        val old = thread ?: return
        old.join(500)
        if (old.isAlive) quarantined = true
        // Never permit another recorder when the original has no release confirmation.
        if (!old.isAlive) {lease?.workerFinished();thread = null}
    }
}
