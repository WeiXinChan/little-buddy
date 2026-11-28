package com.littlebuddy.v2

import com.littlebuddy.v2.parent.PinDiagnostic
import android.annotation.SuppressLint
import android.content.res.AssetManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTimestamp
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.os.Handler
import com.littlebuddy.SpeechDetector
import java.util.concurrent.atomic.AtomicBoolean

/** One recorder throughout wake/continuation and full-duplex interaction.
 * No idle upload. Finite pre-roll preserves the KWS tail and short input onset.
 */
internal class Capture(private val assets: AssetManager, private val owner: Handler,
                       private val client: CaptureSessionPort, private val allowed: () -> Boolean = { true },
                       private val recording: (Boolean)->Unit = {},
                       private val diagnosticScope:PinDiagnostic.Scope=PinDiagnostic.Scope(),
                       private val modelDirectory:java.io.File?=null, private val failed: () -> Unit) {
    constructor(assets:AssetManager,owner:Handler,client:VoiceClient,allowed:()->Boolean={true},
        recording:(Boolean)->Unit={},diagnosticScope:PinDiagnostic.Scope=PinDiagnostic.Scope(),
        modelDirectory:java.io.File?=null,failed:()->Unit):this(assets,owner,ClientCapturePort(client),allowed,recording,diagnosticScope,modelDirectory,failed)
    private val started=AtomicBoolean(false)
    private val cancelled = AtomicBoolean(false)
    @Volatile private var lease:RecorderLease?=null
    private val nativeLock=Any()
    @Volatile private var nativeHandle:AudioRecord?=null
    private val stopRequested=AtomicBoolean(false)
    private val uploads=CaptureUploads({owner.post(it)},android.os.SystemClock::elapsedRealtime,
        { !cancelled.get() && allowed() },{data,speech,at->client.frame(data,speech,at)},
        {requestCancel();owner.post{failed()}})
    @Volatile private var startupHandle:CaptureBootstrap?=null
    @Volatile private var operation=PinDiagnostic.CaptureOperation.NONE
    private var lastOperation=PinDiagnostic.CaptureOperation.NONE
    private var operationBeforeNs=0L
    private var operationAfterNs=0L
    @Volatile private var workerJoined=false
    @Volatile private var thread: Thread? = null
    @Volatile private var stopThread:Thread?=null
    @Volatile var nativeProof = RecorderProof(); private set
    @Volatile var lastClockFailure:CaptureClockFailure?=null;private set
    @Volatile var quarantined = false; private set
    private fun diagnostic(stage:PinDiagnostic.RuntimeStage,joined:Boolean=workerJoined) {
        PinDiagnostic.runtime(PinDiagnostic.RuntimeEvent(stage,diagnosticScope,cancelled=cancelled.get(),
            allowed=runCatching{allowed()}.getOrDefault(false),stopRequested=stopRequested.get(),
            nativeReleased=nativeProof.released,workerJoined=joined,operation=operation))
    }
    /** Fixed scalar trace only for slow operations (or rearm); hard-capped by the adapter. */
    private inline fun <T> measured(kind:PinDiagnostic.CaptureOperation,block:()->T):T {
        val before=System.nanoTime();operation=kind
        try {return block()} finally {
            val after=System.nanoTime();val elapsed=after-before
            lastOperation=kind;operationBeforeNs=before;operationAfterNs=after
            if(elapsed>=20_000_000 || kind==PinDiagnostic.CaptureOperation.KWS_REARM)
                PinDiagnostic.runtime(PinDiagnostic.RuntimeEvent(PinDiagnostic.RuntimeStage.CAPTURE_OPERATION,
                    diagnosticScope,operation=kind,operationNs=elapsed,cancelled=cancelled.get(),
                    allowed=runCatching{allowed()}.getOrDefault(false),stopRequested=stopRequested.get(),nativeReleased=nativeProof.released))
            operation=PinDiagnostic.CaptureOperation.NONE
        }
    }
    fun start() {
        check(started.compareAndSet(false,true) && thread == null && !quarantined)
        lease=ProcessRecorders.acquire("child")
        if(lease==null){PinDiagnostic.event(PinDiagnostic.Stage.CAPTURE_NATIVE,PinDiagnostic.Reason.QUARANTINED);quarantined=true;owner.post{if(allowed())failed()};return}
        diagnostic(PinDiagnostic.RuntimeStage.CAPTURE_START)
        val hold=checkNotNull(lease)
        val worker=Thread({ record() }, "v2-capture");thread=worker
        try {
            worker.start()
            Thread({worker.join();hold.workerFinished();workerJoined=true;diagnostic(PinDiagnostic.RuntimeStage.WORKER_JOINED,true)},"v2-capture-join").start()
        } catch(_:Exception){quarantined=true;requestCancel()}
    }
    @SuppressLint("MissingPermission")
    private fun record() {
        var recorder: AudioRecord? = null
        var aec: AcousticEchoCanceler? = null
        var wake: AbsoluteWake? = null
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
        var ledger:NativeReadLedger?=null
        var startup:CaptureBootstrap?=null
        var uploadSamples = 0
        var step=CaptureReadStep.NONE
        fun upload(batch: List<ShortArray>, speech: Boolean) {
            try {
                step=CaptureReadStep.UPLOAD_ADMIT
                checkNotNull(ledger).check()
                val count=batch.sumOf{it.size}
                if(uploadSamples+count>320000)error("input bound")
                uploadSamples+=count
                if(!client.stage(batch,speech,lastCapturedAt))check(uploads.offer(batch,speech,lastCapturedAt))
            }catch(failure:Exception){batch.forEach{it.fill(0)};throw failure}
        }
        var nativeStartBeforeMs=-1L;var nativeStartAfterMs=-1L
        var nativeReadCalls=0L;var nativeReturnedSamples=0L;var lastNativeReadCount=-1
        fun nativeRead(native:AudioRecord,target:ShortArray):Int {
            operation=PinDiagnostic.CaptureOperation.NATIVE_READ
            nativeReadCalls++
            try {
                val count=native.read(target,0,target.size,AudioRecord.READ_NON_BLOCKING)
                lastNativeReadCount=count
                if(count>0)nativeReturnedSamples=Math.addExact(nativeReturnedSamples,count.toLong())
                return count
            }finally{operation=PinDiagnostic.CaptureOperation.NONE}
        }
        var timestampResult=CaptureTimestampResult.NOT_CALLED
        fun context()=CaptureClockContext(diagnosticScope.activity,diagnosticScope.transport,diagnosticScope.capture,
            step,cancelled.get(),runCatching{allowed()}.getOrDefault(false),stopRequested.get(),nativeProof.released,timestampResult,lastOperation.ordinal,operationBeforeNs,operationAfterNs,
            nativeStartBeforeMs,nativeStartAfterMs,nativeReadCalls,nativeReturnedSamples,lastNativeReadCount,startup?.cachedSamplesTotal ?: 0)
        var diagnosticStage=PinDiagnostic.Stage.CAPTURE_NATIVE
        var attemptedNative=false
        var attemptedWake=false
        try {
            val minimum = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO,
                                                       AudioFormat.ENCODING_PCM_16BIT)
            check(minimum in 1..32000)
            val nativeBytes=maxOf(minimum,6400)
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
            diagnosticStage=PinDiagnostic.Stage.CAPTURE_MODEL
            PinDiagnostic.event(diagnosticStage,PinDiagnostic.Reason.BEGIN)
            attemptedWake=true
            wake = AbsoluteWake(assets,modelDirectory){!cancelled.get() && allowed()}
            measured(PinDiagnostic.CaptureOperation.MODEL_INIT) { wake.initialize() }
            if (cancelled.get() || !allowed()) return
            val timestamp=AudioTimestamp()
            val continuity=NativeReadLedger(nativeBytes/2,CaptureMonotonic::nowMs,
                android.os.SystemClock::elapsedRealtime) {
                timestampResult=CaptureTimestampResult.IN_FLIGHT
                val oldOperation=operation;operation=PinDiagnostic.CaptureOperation.TIMESTAMP
                val code=try {native.getTimestamp(timestamp,AudioTimestamp.TIMEBASE_MONOTONIC)}finally{operation=oldOperation}
                timestampResult=when(code) {AudioRecord.SUCCESS->CaptureTimestampResult.SUCCESS
                    AudioRecord.ERROR_INVALID_OPERATION->CaptureTimestampResult.UNAVAILABLE;else->CaptureTimestampResult.OTHER}
                if(code==AudioRecord.SUCCESS) CaptureStamp(timestamp.framePosition,timestamp.nanoTime) else null
            }
            ledger=continuity
            continuity.diagnostics { error -> CaptureClockDiagnostic.emit(CaptureClockFailure(error.reason,
                continuity.diagnosticEvidence(),error.longWitness,context())) }
            val prefix=CaptureBootstrap(continuity);startup=prefix;startupHandle=prefix
            synchronized(nativeLock){
                if(cancelled.get() || !allowed())return
                measured(PinDiagnostic.CaptureOperation.NATIVE_START) {
                    nativeStartBeforeMs=continuity.armNativeStart()
                    try{native.startRecording()}finally{nativeStartAfterMs=CaptureMonotonic.nowMs()}
                }
            }
            clockCheck(native.recordingState == AudioRecord.RECORDSTATE_RECORDING,CaptureClockReason.RECORDER_NOT_RECORDING)
            nativeProof = RecorderProof(native.audioSessionId, started=true, recording=true)
            runCatching{recording(true)}
            diagnosticStage=PinDiagnostic.Stage.CAPTURE_STARTUP
            PinDiagnostic.event(diagnosticStage,PinDiagnostic.Reason.BEGIN)
            step=CaptureReadStep.STARTUP
            prefix.prepare({target->
                nativeRead(native,target)
            },
                {!cancelled.get() && allowed()},{Thread.sleep(5)})
            diagnosticStage=PinDiagnostic.Stage.CAPTURE_READ
            PinDiagnostic.event(diagnosticStage,PinDiagnostic.Reason.READY)
            while (!cancelled.get() && allowed()) {
                client.check()
                diagnosticStage=PinDiagnostic.Stage.CAPTURE_CLOCK
                step=CaptureReadStep.PRE_ROOM
                val room=continuity.remainingMs()
                diagnosticStage=PinDiagnostic.Stage.CAPTURE_QUEUE
                check(uploads.awaitRoom(frame.size,room)){"capture queue continuity"}
                diagnosticStage=PinDiagnostic.Stage.CAPTURE_CLOCK
                step=CaptureReadStep.AFTER_ROOM
                continuity.check()
                diagnosticStage=PinDiagnostic.Stage.CAPTURE_READ
                val replay=prefix.pending
                step=if(replay)CaptureReadStep.PREFIX_REPLAY else CaptureReadStep.NATIVE_READ
                val count=if(replay)prefix.take(frame) else {
                    nativeRead(native,frame)
                }
                if(cancelled.get() || !allowed())break
                check(count in 0..frame.size)
                diagnosticStage=PinDiagnostic.Stage.CAPTURE_CLOCK
                step=CaptureReadStep.POST_READ
                lastCapturedAt=if(replay)continuity.sampleTime(prefix.replayPosition) else continuity.read(count)
                if (count == 0) { Thread.sleep(5); continue }
                clockCheck(native.recordingState == AudioRecord.RECORDSTATE_RECORDING,CaptureClockReason.RECORDER_NOT_RECORDING)
                nativeProof = nativeProof.copy(recording=true, frames=nativeProof.frames+count)
                buffered.push(frame, count)
                position = buffered.position
                if (awake && idle != client.idleSerial) {
                    idle = client.idleSerial
                    awake = false; voiced = false; uploadSamples = 0
                    detector = SpeechDetector(320, initialFloor = 36.0); wakeBase = wakeOrigin(position,count)
                    // Model/cache IO is forbidden on this running-recorder rearm path.
                    diagnosticStage=PinDiagnostic.Stage.CAPTURE_KWS;step=CaptureReadStep.KWS_REARM
                    measured(PinDiagnostic.CaptureOperation.KWS_REARM) { checkNotNull(wake).rearm() }
                    diagnosticStage=PinDiagnostic.Stage.CAPTURE_CLOCK;step=CaptureReadStep.POST_REARM
                    continuity.check()
                }
                if (!awake) {
                    detector.accept(frame,count)
                    if(detector.detectedSpeechInRead)client.speechBeforeWake()
                    if(cancelled.get() || !allowed())break
                    diagnosticStage=PinDiagnostic.Stage.CAPTURE_KWS
                    step=CaptureReadStep.KWS
                    operation=PinDiagnostic.CaptureOperation.KWS
                    val candidate=measured(PinDiagnostic.CaptureOperation.KWS) { wake?.accept(frame,count) }
                    step=CaptureReadStep.POST_KWS
                    diagnosticStage=PinDiagnostic.Stage.CAPTURE_CLOCK
                    continuity.check()
                    val tail=candidate ?: continue
                    if(cancelled.get() || !allowed())break
                    awake = true
                    // Keep the model owned until recorder release; next idle uses a fresh stream.

                    detector = SpeechDetector(320, initialFloor = 36.0)
                    continuity.check()
                    diagnosticStage=PinDiagnostic.Stage.CAPTURE_KWS
                    val absoluteTail=Math.addExact(wakeBase,tail)
                    check(tail>=0 && absoluteTail in wakeBase..position) {"keyword capture coordinate"}
                    diagnosticStage=PinDiagnostic.Stage.CAPTURE_CLOCK
                    val wakeBoundary=continuity.sampleTime(absoluteTail)
                    check(wakeBoundary>=0)
                    val observedPosition=position
                    val relativeWakeMs=wakeBoundary-continuity.sampleTime(0)
                    val boundary=WakeBoundary(wakeBoundary,absoluteTail,observedPosition,relativeWakeMs)
                    client.stageWake(boundary)
                    owner.post { if (!cancelled.get() && allowed()) client.wake(boundary) }
                    // Absolute ring and KWS-local coordinates share a recorded origin.
                    lastSpeech = android.os.SystemClock.elapsedRealtime()
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
        } catch (error: Exception) {
            if(error is CaptureClockFailure){
                val failure=CaptureClockFailure(error.reason,error.evidence,error.longWitness,context())
                lastClockFailure=failure;CaptureClockDiagnostic.emit(failure)
            }
            diagnostic(PinDiagnostic.RuntimeStage.CAPTURE_FAILURE)
            if (!cancelled.get()) PinDiagnostic.runtimeError(diagnosticStage,error)
            if (!cancelled.get()) owner.post { if(!cancelled.get() && allowed())failed() }
        } finally {
            step=CaptureReadStep.CLEANUP;operation=PinDiagnostic.CaptureOperation.CLEANUP
            uploads.cancel();frame.fill(0);startup?.clear();startupHandle=null;buffered.clear();runCatching{recording(false)}
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
            diagnostic(PinDiagnostic.RuntimeStage.CAPTURE_RELEASE)
            var disposed=true
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
        cancelled.set(true);client.cancel();startupHandle?.clear();uploads.cancel()
        diagnostic(PinDiagnostic.RuntimeStage.CAPTURE_CANCEL)
        if(!stopRequested.compareAndSet(false,true))return
        val hold=lease ?: return
        if(!hold.beginStop())return
        val stopper=Thread({diagnostic(PinDiagnostic.RuntimeStage.CAPTURE_STOP_BEGIN);try { synchronized(nativeLock) {
            nativeHandle?.let {if(it.recordingState==AudioRecord.RECORDSTATE_RECORDING)it.stop()}
        }}catch(_:Exception){quarantined=true}finally{hold.endStop();diagnostic(PinDiagnostic.RuntimeStage.CAPTURE_STOP_END)}},"v2-capture-stop")
        stopThread=stopper;stopper.start()
    }
    fun close() {
        requestCancel()
        val until=System.nanoTime()+500_000_000L
        val old = thread ?: return
        fun waitFor(worker:Thread?) {
            if(worker==null)return
            val left=(until-System.nanoTime())/1_000_000
            if(left>0)worker.join(left)
            if(worker.isAlive)quarantined=true
        }
        waitFor(old);waitFor(stopThread)
        // Never permit another recorder when the original has no release confirmation.
        if (!old.isAlive) {lease?.workerFinished();workerJoined=true;thread = null}
    }
}
