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
import java.util.concurrent.atomic.AtomicLong

internal data class CaptureHooks(val beforeDecode: ()->Unit = {},val beforeDispose: ()->Unit = {},val beforeCommandDecision: (String?)->Unit = {},val beforeLeaseReturn:()->Unit = {},val syntheticTrace:((String)->Unit)?=null,val syntheticEnabled:()->Boolean={false},val syntheticPcm:((ShortArray,Int,RecorderProof)->Unit)?=null)

internal enum class CapturePhase { NOT_STARTED, THREAD_START, AUDIO_RECORD, WAKE_KWS, MANAGEMENT_KWS, START, READ, RELEASE, RELEASED, QUARANTINED }

/** One recorder throughout wake/continuation and full-duplex interaction.
 * No idle upload. Finite pre-roll preserves the KWS tail and short input onset.
 */
internal class Capture(private val assets: AssetManager, private val owner: Handler,
                       private val client: VoiceClient, private val failed: () -> Unit,
                       private val managementChanged: (Boolean) -> Unit = {},
                       private val allowed: ()->Boolean = { true },
                       private val trace: (String,RecorderProof,String)->Unit = { _,_,_-> },
                       private val hooks: CaptureHooks = CaptureHooks(),
                       private val disposed: ()->Unit = {},
                       private val managementPrompt: (String,()->Boolean,(Boolean)->Unit)->Unit = {_,_,_->}) {
    companion object {
        private val lease=java.util.concurrent.atomic.AtomicReference<String?>(null)
        private val leaseLock=Any()
        private val leaseWaiters=linkedSetOf<()->Unit>()
        val leaseAvailable get()=lease.get()==null
        fun whenLeaseAvailable(callback:()->Unit):()->Unit {
            val immediate=synchronized(leaseLock){leaseWaiters.add(callback);if(leaseAvailable){leaseWaiters.remove(callback);true}else false}
            if(immediate)callback()
            return {synchronized(leaseLock){leaseWaiters.remove(callback)};Unit}
        }
        private fun signalLeaseAvailable(){val ready=synchronized(leaseLock){if(leaseAvailable)leaseWaiters.toList().also{leaseWaiters.clear()}else emptyList()};ready.forEach{it()}}
    }
    private val captureId=java.util.UUID.randomUUID().toString()
    val leaseReturned get()=!ownsLease && lease.get()!=captureId
    @Volatile private var operation="NOT_STARTED"
    @Volatile private var progressAt=0L
    private fun progress(value:String){operation=value;progressAt=android.os.SystemClock.elapsedRealtime();if(value.contains("MODEL_") || value.contains("STREAM_"))trace(value,nativeProof,"capture=$captureId")}
    fun workerEvidence()="operation=$operation lastProgressMs=$progressAt cancelled=${cancelled.get()} workerAlive=${thread?.isAlive} captureId=$captureId leaseOwner=${lease.get()} ownsLease=$ownsLease stack="+(thread?.stackTrace?.take(12)?.joinToString("|") ?: "none")
    @Volatile private var ownsLease=false
    private val closeWaited=AtomicBoolean(false)
    private val nativeLock=Any()
    @Volatile private var nativeRecorder: AudioRecord? = null
    @Volatile private var capturedSamples=0L
    private data class PromptAck(val nonce:Long,val nano:Long,val generation:Long,val success:Boolean,val completedAtMs:Long)
    private val promptPermit=ManagementPromptPermit(android.os.SystemClock::elapsedRealtime)
    private val promptAck=java.util.concurrent.atomic.AtomicReference<PromptAck?>(null)
    private val commandGeneration = AtomicLong(0)
    @Volatile private var management = false
    fun enterManagement() { commandGeneration.incrementAndGet(); management = true; uploads.invalidate() }
    fun exitManagement() { commandGeneration.incrementAndGet(); management = false; uploads.invalidate() }
    @Volatile var phase = CapturePhase.NOT_STARTED; private set
    @Volatile var failedPhase: CapturePhase? = null; private set
    private val cancelled = AtomicBoolean(false)
    private val uploads=CaptureUploads(
        post={task->owner.post(task)},
        eligible={ticket->!cancelled.get() && allowed() && !management && ticket==commandGeneration.get()},
        deliver={data,speech,time->client.frame(data,speech,time)},
        failed={e->trace("UPLOAD_DELIVERY_EXCEPTION",nativeProof,SafeFailure.describe(e));failedPhase=phase;requestStop();failed()},
        waiting={trace("UPLOAD_BACKPRESSURE",nativeProof,"sampleCapacity=16000")})
    private var thread: Thread? = null
    @Volatile var nativeProof = RecorderProof(); private set
    @Volatile private var resourceFault = false
    @Volatile private var pendingDisposal = false
    val resourceFailed get() = resourceFault
    val quarantined get() = resourceFault || (pendingDisposal && thread?.isAlive == true)
    val closing get() = cancelled.get()
    val workerDone get() = thread?.isAlive != true
    fun start(): Boolean {
        if(thread != null || quarantined || cancelled.get() || !allowed()) { trace("START_REJECTED",nativeProof,phase.name); return false }
        if(!lease.compareAndSet(null,captureId)) { trace("START_LEASE_BUSY",nativeProof,phase.name); return false }
        ownsLease=true
        trace("LEASE_ACQUIRE",nativeProof,captureId)
        phase = CapturePhase.THREAD_START
        thread = Thread({ record() }, "v2-capture").apply { start() }
        return true
    }
    @SuppressLint("MissingPermission")
    private fun record() {
        var recorder: AudioRecord? = null
        var aec: AcousticEchoCanceler? = null
        var wake: SherpaWake? = null
        var commands: SherpaWake? = null
        val commandBoundary=CommandBoundary(diagnostic={detail->hooks.syntheticTrace?.invoke(detail)})
        val buffered = WakeSamples()
        val frame = ShortArray(320)
        var activePromptNonce=-1L
        var suppressPrompt=false
        var suppressStartedAt=0L
        var awaitingPrompt:PromptAck?=null
        val captureTimestamp=android.media.AudioTimestamp()
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
        val meter=SyntheticCaptureMeter()
        fun upload(data: List<ShortArray>, speech: Boolean) {
            val samples=data.sumOf{it.size}
            val ticket=commandGeneration.get()
            if(uploadSamples+samples>320000)error("input bound")
            progress("UPLOAD_ENQUEUE")
            if(uploads.submit(data,speech,ticket,android.os.SystemClock.elapsedRealtime()))uploadSamples+=samples
        }
        try {
            if(cancelled.get() || !allowed())return
            phase = CapturePhase.AUDIO_RECORD
            val minimum = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO,
                                                       AudioFormat.ENCODING_PCM_16BIT)
            check(minimum in 1..32000)
            val native = AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION, 16000,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(minimum, 6400))
            recorder = native
            synchronized(nativeLock) { nativeRecorder=native }
            check(native.state == AudioRecord.STATE_INITIALIZED)
            if (AcousticEchoCanceler.isAvailable()) {
                aec = AcousticEchoCanceler.create(native.audioSessionId)
                aec?.enabled = true // Availability/enabled are diagnostics, not acoustic PASS.
            }
            phase = CapturePhase.WAKE_KWS
            wake = SherpaWake(assets, allowed={ !cancelled.get() && allowed() }, progress={progress("WAKE_$it")})
            if(cancelled.get() || !allowed())return
            phase = CapturePhase.MANAGEMENT_KWS
            commands = SherpaWake(assets, "*", "wake/manage.txt", 8, { !cancelled.get() && allowed() }, {progress("MANAGEMENT_$it")})
            synchronized(nativeLock) {
                if (cancelled.get() || !allowed()) return
                phase = CapturePhase.START
                native.startRecording()
                check(native.recordingState == AudioRecord.RECORDSTATE_RECORDING)
                nativeProof = RecorderProof(native.audioSessionId, started=true, recording=true)
                trace("NATIVE_START",nativeProof,phase.name)
            }
            phase = CapturePhase.READ
            if(hooks.syntheticEnabled())hooks.syntheticTrace?.invoke("NATIVE_FORMAT rate=${native.sampleRate} channels=${native.channelCount} encoding=${native.audioFormat} bufferFrames=${native.bufferSizeInFrames} source=${native.audioSource} hardware=${android.os.Build.HARDWARE}")
            while (!cancelled.get()) {
                progress("NATIVE_READ")
                val count = native.read(frame, 0, frame.size, AudioRecord.READ_NON_BLOCKING)
                if (cancelled.get() || !allowed()) break
                if(count<0)trace("NATIVE_READ_ERROR",nativeProof,"result=$count")
                check(count >= 0)
                if (count == 0) { Thread.sleep(5); continue }
                val accept=synchronized(nativeLock) {
                    if(cancelled.get() || !allowed()) false else {
                        check(native.recordingState==AudioRecord.RECORDSTATE_RECORDING)
                        nativeProof=nativeProof.copy(recording=true,frames=nativeProof.frames+count)
                        true
                    }
                }
                if(!accept)break
                progress("BEFORE_DECODE")
                capturedSamples+=count
                if(hooks.syntheticEnabled())hooks.syntheticPcm?.invoke(frame,count,nativeProof)
                if(hooks.syntheticEnabled())meter.accept(frame,count)?.let{hooks.syntheticTrace?.invoke("$it source=VOICE_COMMUNICATION route=${native.routedDevice?.type} aec=${aec?.enabled}")}
                val completedPrompt=promptAck.getAndSet(null)?.takeIf{it.nonce==activePromptNonce && it.generation==commandGeneration.get()}
                if(completedPrompt!=null)promptPermit.revoke(completedPrompt.nonce,completedPrompt.generation)
                if(completedPrompt?.success==false){
                    commandBoundary.rejectConfirmation();suppressPrompt=false
                    if(!checkNotNull(commands).resetAt(capturedSamples))break
                    commandBoundary.skip(count);frame.fill(0);continue
                }
                if(suppressPrompt){
                    val published=completedPrompt!=null && commandBoundary.awaitingPromptCompletion && commandBoundary.promptComplete(completedPrompt.nonce,completedPrompt.generation,completedPrompt.completedAtMs)
                    commandBoundary.skip(count)
                    if(completedPrompt!=null){
                        if(!checkNotNull(commands).resetAt(capturedSamples))break
                        if(published && commandBoundary.confirmationPending)awaitingPrompt=completedPrompt
                        suppressPrompt=false
                        trace("PROMPT_FEATURES_DROPPED",nativeProof,"origin=$capturedSamples")
                    } else if(android.os.SystemClock.elapsedRealtime()-suppressStartedAt>=8000){
                        commandBoundary.rejectConfirmation();suppressPrompt=false
                        if(!checkNotNull(commands).resetAt(capturedSamples))break
                        trace("PROMPT_PREPARATION_TIMEOUT",nativeProof,"local")
                    }
                    frame.fill(0);continue
                }
                if(completedPrompt?.success==true && commandBoundary.promptComplete(completedPrompt.nonce,completedPrompt.generation,completedPrompt.completedAtMs))awaitingPrompt=completedPrompt
                hooks.beforeDecode()
                if(cancelled.get() || !allowed())break
                val commandTail=commands?.accept(frame,count)
                val hit=if(commandTail!=null) CommandBoundary.Hit(checkNotNull(commands?.detectedKeyword),checkNotNull(commands).matchedStart,commandTail) else null
                if(hit!=null)hooks.syntheticTrace?.invoke("KWS name=${hit.name} start=${hit.start} end=${hit.end} sample=$capturedSamples paths=8 score=1.5 threshold=.25 trailing=2")
                hooks.beforeCommandDecision(hit?.name)
                if(cancelled.get() || !allowed())break
                progress("COMMAND_BOUNDARY")

                awaitingPrompt?.let{ack ->
                    progress("CONFIRM_NATIVE_TIMESTAMP")
                    val result=native.getTimestamp(captureTimestamp,android.media.AudioTimestamp.TIMEBASE_MONOTONIC)
                    val marker=if(result==AudioRecord.SUCCESS)CaptureFreshness.marker(ack.nano,captureTimestamp.framePosition,captureTimestamp.nanoTime,nativeProof.frames,System.nanoTime()) else null
                    if(marker!=null && ack.generation==commandGeneration.get()) {
                        val armed=commandBoundary.armConfirmation(ack.nonce,marker,ack.generation)
                        trace(if(armed)"CONFIRM_NATIVE_BARRIER" else "CONFIRM_NATIVE_BARRIER_REJECTED",nativeProof,"nonce=${ack.nonce} nativeFrame=$marker nativeNano=${captureTimestamp.nanoTime} promptNano=${ack.nano}")
                        awaitingPrompt=null
                    }
                }
                val command=commandBoundary.frame(frame,count,hit,management,commandGeneration.get())
                if(command in listOf("确认退出提示","继续管理")) {
                    suppressPrompt=true;suppressStartedAt=android.os.SystemClock.elapsedRealtime()
                    val ticket=commandGeneration.get();val nonce=commandBoundary.confirmationNonce;activePromptNonce=nonce;promptPermit.offer(nonce,ticket)
                    owner.post {if(!cancelled.get() && allowed() && management && ticket==commandGeneration.get())managementPrompt(if(command=="确认退出提示")"要退出吗？请说确认退出，或点取消按钮。" else "继续管理",{!cancelled.get() && allowed() && ticket==commandGeneration.get() && promptPermit.valid(nonce,ticket)}) {success ->if(!cancelled.get() && allowed() && ticket==commandGeneration.get()){promptAck.set(PromptAck(nonce,System.nanoTime(),ticket,success,android.os.SystemClock.elapsedRealtime()))}}}
                    frame.fill(0);continue
                }
                if (command!=null) {
                    val entering = !management && command == "进入管理"
                    val exiting = management && command in listOf("取消", "退出管理")
                    if (entering || exiting) {
                        trace(if(entering)"MANAGEMENT_ENTER" else "MANAGEMENT_EXIT",nativeProof,phase.name)
                        commandGeneration.incrementAndGet()
                        management = entering
                        uploads.invalidate()
                        buffered.clear(); awake = false; voiced = false; uploadSamples = 0
                        if(cancelled.get() || !allowed())break
                        progress("WAKE_STREAM_RESET")
                        if(wake?.resetAt(buffered.position)!=true)break; wakeBase = 0
                        owner.post { if (!cancelled.get() && allowed()) {
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
                    detector = SpeechDetector(320, initialFloor = 36.0); wakeBase = 0
                    if(cancelled.get() || !allowed())break
                        progress("WAKE_STREAM_RESET")
                        if(wake?.resetAt(buffered.position)!=true)break
                    continue
                }
                if (!awake) {
                    val tail = wake?.accept(frame, count) ?: continue
                    if (!client.connectionActive) {
                        // Unconfigured local KWS never builds/uploads child expressions.
                        owner.post { if (!cancelled.get() && allowed()) client.wake() }
                        if(cancelled.get() || !allowed())break
                        progress("WAKE_STREAM_RESET")
                        if(wake?.resetAt(buffered.position)!=true)break
                        wakeBase = 0; buffered.clear()
                        continue
                    }
                    awake = true
                    if(cancelled.get() || !allowed())break
                    // Keep the model; the next idle/management boundary resets its stream.
                    detector = SpeechDetector(320, initialFloor = 36.0)
                    val wakeBoundary = (android.os.SystemClock.elapsedRealtime() -
                        ((position - (wakeBase + tail).coerceIn(0, position)) * 1000 / 16000)).coerceAtLeast(0)
                    owner.post { if (!cancelled.get() && allowed()) client.wake(wakeBoundary) }
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
                        upload(buffered.read(),true)
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
                        upload(buffered.read(),true)
                    } else upload(buffered.read(),true)
                } else if (voiced && now - lastSpeech <= 300) {
                    upload(buffered.read(),false)
                } else {
                    owner.post { if (!cancelled.get() && allowed()) client.quiet() }
                    if (voiced) { voiced = false; detector = SpeechDetector(320, initialFloor = 36.0) }
                    if (!firstAfterWake) buffered.follow()
                }
                // Per-expression audio is bounded. Endpoint completion resets it via
                // the owner callback; the backend separately retains the 600s session.
                if (uploadSamples >= 300000) error("input capacity")
            }
        } catch (e: Exception) {
            trace("CAPTURE_EXCEPTION",nativeProof,"phase=${phase.name} operation=$operation ${SafeFailure.describe(e)}")
            if(operation.contains("STREAM_") || operation.contains("MODEL_"))resourceFault=true
            failedPhase = phase
            if (!cancelled.get()) owner.post { failed() }
        } finally {
            progress("FINALLY_ENTER")
            trace("FINALLY_ENTER",nativeProof,operation)
            phase = CapturePhase.RELEASE
            uploads.close()
            frame.fill(0); buffered.clear()
            // Stop/release native collection before potentially slow model destruction.
            stopNative()
            synchronized(nativeLock) {
                try {
                    trace("NATIVE_RELEASE_BEGIN",nativeProof,phase.name)
                    progress("NATIVE_RELEASE")
                    recorder?.release()
                    check(recorder == null || recorder?.state == AudioRecord.STATE_UNINITIALIZED)
                    nativeRecorder=null
                    nativeProof=nativeProof.copy(recording=false,released=true)
                    trace("NATIVE_RELEASE_END",nativeProof,phase.name)
                } catch (_: Exception) { resourceFault=true }
            }
            try { aec?.release() } catch (_: Exception) { resourceFault=true }
            trace("MODELS_DISPOSE_BEGIN",nativeProof,phase.name)
            hooks.beforeDispose()
            try { commands?.close() } catch (_: Exception) { resourceFault=true }
            try { wake?.close() } catch (_: Exception) { resourceFault=true }
            trace("MODELS_DISPOSE_END",nativeProof,phase.name)
            pendingDisposal=false
            phase = if (quarantined) CapturePhase.QUARANTINED else CapturePhase.RELEASED
            val completedWorker=Thread.currentThread()
            Thread({
                completedWorker.join()
                hooks.beforeLeaseReturn()
                // No JNI here: model/native cleanup is over and worker really ended.
                if(ownsLease && !resourceFault){check(lease.compareAndSet(captureId,null));ownsLease=false;trace("LEASE_RETURN",nativeProof,captureId);signalLeaseAvailable()}
                disposed()
            },"v2-capture-completion").start()
            if (!cancelled.get()) owner.post { failed() }
        }
    }
    private fun stopNative() { synchronized(nativeLock) {
        val native=nativeRecorder ?: return
        try {
            trace("NATIVE_STOP_BEGIN",nativeProof,phase.name)
            if(native.recordingState==AudioRecord.RECORDSTATE_RECORDING)native.stop()
            check(native.recordingState==AudioRecord.RECORDSTATE_STOPPED)
            nativeProof=nativeProof.copy(recording=false,stopped=true)
            trace("NATIVE_STOP_END",nativeProof,phase.name)
        } catch (_: Exception) { resourceFault=true }
    } }
    /** Immediate caller-thread cancellation, independent of owner/decode/destructors. */
    fun requestStop() {
        if(!cancelled.compareAndSet(false,true))return
        commandGeneration.incrementAndGet()
        trace("CANCEL_REQUEST",nativeProof,phase.name)
        stopNative()
        uploads.close()
    }
    fun close() {
        requestStop()
        val old = thread ?: return
        if(!closeWaited.compareAndSet(false,true))return
        old.join(500)
        if (old.isAlive) { pendingDisposal = true; trace("DISPOSE_QUARANTINE",nativeProof,operation) }
        // Never permit another recorder when the original has no release confirmation.
        if (!old.isAlive) thread = null
    }
}
