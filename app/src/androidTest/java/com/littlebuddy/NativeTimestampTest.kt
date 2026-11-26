package com.littlebuddy

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.Application
import android.app.KeyguardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTimestamp
import android.media.MediaRecorder
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.os.SystemClock
import android.view.WindowManager
import android.widget.TextView
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.AndroidJUnitRunner
import com.littlebuddy.v2.CaptureMonotonic
import com.littlebuddy.v2.CaptureStamp
import com.littlebuddy.v2.NativeReadLedger
import com.littlebuddy.v2.CaptureBootstrap
import com.littlebuddy.v2.ProcessRecorders
import com.littlebuddy.v2.RecorderLease
import org.junit.AssumptionViolatedException
import org.junit.Test
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Separate, explicitly selected instrumentation entry. No change to the default runner or APK.
 * The target's declared component/UID is used, but neither its Application nor business Activity
 * is constructed. No owner permission is granted: this test only exercises a native recorder port.
 */
class NativeTimestampRunner : AndroidJUnitRunner() {
    companion object {
        const val METHOD="com.littlebuddy.NativeTimestampTest#nativeTimestampAndProductionLedger"
        const val STARTUP_METHOD="com.littlebuddy.NativeTimestampStartupTest#compareTimestampStartup"
        const val CADENCE_METHOD="com.littlebuddy.NativeTimestampCadenceTest#observeOneBoundedCadence"
        const val TARGET="com.littlebuddy.V2VoiceActivity"
    }
    override fun newApplication(loader:ClassLoader,name:String,context:Context):Application =
        super.newApplication(loader,Application::class.java.name,context)
    override fun onCreate(arguments:Bundle?) {
        val selected=Bundle(arguments ?: Bundle())
        val selectedClass=selected.getString("class")
        require(selectedClass in setOf(METHOD,STARTUP_METHOD,CADENCE_METHOD) &&
            (selectedClass!=CADENCE_METHOD || selected.getString("nativeTimestampCadenceDiagnostic")=="true") &&
            (selectedClass!=STARTUP_METHOD || selected.getString("nativeTimestampStartupDiagnostic")=="true") && selected.getString("nativeTimestampProbe")=="true" &&
            selected.getString("businessIdlePreflight")=="true") { "native probe requires exact class and host idle preflight" }
        selected.putString("disableAnalytics","true")
        super.onCreate(selected)
    }
    override fun newActivity(loader:ClassLoader,name:String,intent:Intent):Activity {
        check(name==TARGET && intent.getBooleanExtra("nativeTimestampOnly",false)) { "business Activity forbidden in native probe" }
        return NativeTimestampForegroundActivity()
    }
}

/** Not declared as a test-package Activity: runner substitutes the target component's instance. */
class NativeTimestampForegroundActivity : Activity() {
    @Volatile var active=false;private set
    @Volatile var focused=false;private set
    @Volatile var cancelNative:(()->Unit)?=null
    override fun onCreate(state:Bundle?) {
        super.onCreate(state)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        setContentView(TextView(this).apply {
            text="本机麦克风时间戳检查\n不保存声音，不连接业务服务。";isSaveEnabled=false;textSize=22f
        })
    }
    override fun onResume(){super.onResume();active=true}
    override fun onPause(){active=false;cancelNative?.invoke();super.onPause()}
    override fun onWindowFocusChanged(hasFocus:Boolean){super.onWindowFocusChanged(hasFocus);focused=hasFocus;if(!hasFocus)cancelNative?.invoke()}
    override fun onDestroy(){active=false;cancelNative?.invoke();super.onDestroy()}
}

internal class NativeDependency(val code:String):AssumptionViolatedException(code)
internal class ProbeMetadata {
    @Volatile var outcome="NOT_EXECUTED"
    @Volatile var reason=""
    @Volatile var exceptionClass=""
    @Volatile var nativeExceptionClass=""
    @Volatile var stopExceptionClass=""
    @Volatile var dependencyReason=""
    @Volatile var resultJson=""
    @Volatile var ownedLeaseComplete=false
    @Volatile var phase="preflight"
    @Volatile var failurePhase=""
    @Volatile var targetVersion=0
    @Volatile var lastReadCode=Int.MIN_VALUE
    @Volatile var minimumBytes=0
    @Volatile var nativeBytes=0
    @Volatile var actualBufferFrames=0
    @Volatile var startCallMs=0L
    @Volatile var startDurationMs=-1L
    @Volatile var firstApiSuccessMs=-1L
    @Volatile var firstLedgerReadyMs=-1L
    @Volatile var runMs=0L
    @Volatile var timestampCalls=0L
    @Volatile var timestampSuccess=0L
    @Volatile var timestampUnavailable=0L
    @Volatile var lastApiCode=Int.MIN_VALUE
    @Volatile var maxApiNs=0L
    @Volatile var maxStampAgeNs=Long.MIN_VALUE
    @Volatile var minStampAgeNs=Long.MAX_VALUE
    @Volatile var lastStampFrames=-1L
    @Volatile var lastStampNs=-1L
    @Volatile var lastPairDeltaFrames=0L
    @Volatile var lastPairDeltaNs=0L
    @Volatile var positiveReads=0L
    @Volatile var emptyReads=0L
    @Volatile var samplesRead=0L
    @Volatile var minRoomMs=Long.MAX_VALUE
    @Volatile var lastRoomMs=-1L
    @Volatile var lastSampleBootMs=-1L
    @Volatile var nativeAttempted=false
    @Volatile var started=false
    @Volatile var stopped=false
    @Volatile var released=false
    @Volatile var workerJoined=false
    @Volatile var stopTaskJoined=true
    @Volatile var foreground=false
    @Volatile var permission=false
    @Volatile var locked=false
    @Volatile var lease="not_acquired"
    @Synchronized fun snapshot()=Bundle().apply {
        putString("v2_timestamp_outcome",outcome);putString("v2_timestamp_reason",reason)
        putString("v2_timestamp_exception",exceptionClass);putString("v2_timestamp_phase",phase)
        putString("native_exception_class",nativeExceptionClass);putString("stop_request_exception_class",stopExceptionClass)
        putString("dependency_reason",dependencyReason);putString("v2_timestamp_result_json",resultJson)
        putBoolean("owned_lease_complete",ownedLeaseComplete)
        putString("failure_phase",failurePhase);putInt("target_version_code",targetVersion);putInt("last_read_code",lastReadCode)
        putInt("sdk",Build.VERSION.SDK_INT);putInt("minimum_bytes",minimumBytes);putInt("native_bytes",nativeBytes)
        putInt("actual_buffer_frames",actualBufferFrames);putLong("start_duration_ms",startDurationMs)
        putLong("first_api_success_ms",firstApiSuccessMs);putLong("first_ledger_ready_ms",firstLedgerReadyMs)
        putLong("continuous_run_ms",runMs);putLong("timestamp_calls",timestampCalls)
        putLong("timestamp_success",timestampSuccess);putLong("timestamp_unavailable",timestampUnavailable)
        putInt("last_api_code",lastApiCode);putLong("max_api_ns",maxApiNs)
        putLong("max_stamp_age_ns",maxStampAgeNs);putLong("min_stamp_age_ns",minStampAgeNs)
        putLong("last_stamp_frames",lastStampFrames);putLong("last_stamp_ns",lastStampNs)
        putLong("last_pair_delta_frames",lastPairDeltaFrames);putLong("last_pair_delta_ns",lastPairDeltaNs)
        putLong("positive_reads",positiveReads);putLong("empty_reads",emptyReads);putLong("samples_read",samplesRead)
        putLong("min_remaining_room_ms",minRoomMs);putLong("last_remaining_room_ms",lastRoomMs)
        putLong("last_sample_boot_ms",lastSampleBootMs);putBoolean("native_attempted",nativeAttempted)
        putBoolean("recording_started",started);putBoolean("native_stopped",stopped);putBoolean("native_released",released)
        putBoolean("worker_joined",workerJoined);putBoolean("stop_task_joined",stopTaskJoined)
        putBoolean("foreground",foreground);putBoolean("record_audio_permission",permission);putBoolean("locked",locked)
        putString("recorder_lease",lease)
    }
}

/** Native-only counterpart to production cancellation. Never closes/replaces another owner's recorder. */
internal class ProbeControl(private val lease:RecorderLease,private val meta:ProbeMetadata) {
    val cancelled=AtomicBoolean(false)
    private val startup=ProbeStartupCancellation(cancelled)
    fun installStartup(prefix:CaptureBootstrap){startup.install(prefix)}
    private val lock=Any()
    private val stopOnce=AtomicBoolean(false)
    val stopFailure=AtomicReference<String?>(null)
    private var native:AudioRecord?=null
    @Volatile private var stopper:Thread?=null
    fun install(value:AudioRecord){synchronized(lock){native=value}}
    fun start(){synchronized(lock){check(!cancelled.get());checkNotNull(native).startRecording()}}
    fun cancel(){
        startup.cancel()
        if(!stopOnce.compareAndSet(false,true) || !lease.beginStop())return
        val work=Thread({
            try {guardedProbeStop({synchronized(lock){native?.let{if(it.recordingState==AudioRecord.RECORDSTATE_RECORDING)it.stop()}}}) {
                stopFailure.compareAndSet(null,it);meta.stopExceptionClass=it
            }}finally{lease.endStop()}
        },"native-timestamp-stop")
        stopper=work
        guardedProbeStop({work.start()}){stopFailure.compareAndSet(null,it);meta.stopExceptionClass=it;lease.endStop()}
    }
    fun release(){startup.clear();synchronized(lock){
        val value=native
        if(value==null){if(!meta.nativeAttempted){meta.stopped=true;meta.released=true;lease.nativeReleased()};return}
        try {
            try {if(value.recordingState==AudioRecord.RECORDSTATE_RECORDING)value.stop()
                check(value.recordingState==AudioRecord.RECORDSTATE_STOPPED);meta.stopped=true
            }finally{
                value.release();check(value.state==AudioRecord.STATE_UNINITIALIZED)
                meta.released=true;lease.nativeReleased()
            }
        }finally{native=null}
    }}
    fun joinStop(){stopper?.join(1500);meta.stopTaskJoined=stopper?.isAlive!=true}
}

class NativeTimestampTest {
    private val instrumentation get()=InstrumentationRegistry.getInstrumentation()
    private val context get()=instrumentation.targetContext
    private fun dependency(code:String):Nothing=throw NativeDependency(code)
    private fun allowed(activity:NativeTimestampForegroundActivity)=activity.active && activity.focused &&
        !context.getSystemService(KeyguardManager::class.java).isKeyguardLocked &&
        context.getSystemService(PowerManager::class.java).isInteractive &&
        context.checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED
    private fun emit(meta:ProbeMetadata){instrumentation.sendStatus(7,meta.snapshot())}
    private fun safeReason(error:Throwable):String {
        if(error is NativeDependency)return error.code
        // Production ledger reasons contain no material. Never output arbitrary native exception text.
        val reasons=setOf("capture clock regressed","capture clock regressed during timestamp","capture timebase changed",
            "invalid capture timestamp","capture timestamp regressed","incoherent capture time","capture rate outside bound",
            "capture timestamp relabeled","capture timestamp unavailable","capture timestamp stale",
            "cumulative native continuity exhausted","cumulative native room exhausted","capture timestamp not ready",
            "native read exceeds timestamp position","insufficient continuous reads","native release unconfirmed",
            "native probe worker did not finish","native buffer smaller than requested","native format mismatch","capture startup deadline","startup native continuity exhausted",
            "startup native room exhausted","startup samples outside bound","capture startup counter outside bound",
            "capture startup origin unproven","capture startup anchor unconfirmed","capture startup cache exhausted",
            "capture startup cancelled","invalid startup read")
        return error.message?.takeIf{it in reasons} ?: "NATIVE_PROBE_FAILED"
    }
    @SuppressLint("MissingPermission")
    @Test fun nativeTimestampAndProductionLedger(){
        val meta=ProbeMetadata()
        var failure:Throwable?=null
        var cleanupClass=""
        var verdict:ProbeDecision?=null
        var activity:NativeTimestampForegroundActivity?=null
        var lease:RecorderLease?=null
        var control:ProbeControl?=null
        var worker:Thread?=null
        val workerFailure=AtomicReference<Throwable?>()
        val workerCleanupFailure=AtomicReference<String?>(null)
        try {
            if(instrumentation !is NativeTimestampRunner)dependency("DEPENDENCY_EXPLICIT_NATIVE_RUNNER_REQUIRED")
            if(context.applicationContext.javaClass!=Application::class.java)dependency("DEPENDENCY_TARGET_APPLICATION_NOT_ISOLATED")
            check(context.packageName=="com.littlebuddy.sim.v2")
            meta.targetVersion=context.packageManager.getPackageInfo(context.packageName,0).versionCode
            meta.permission=context.checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED
            meta.locked=context.getSystemService(KeyguardManager::class.java).isKeyguardLocked
            if(!meta.permission)dependency("DEPENDENCY_RECORD_AUDIO_PERMISSION")
            if(meta.locked || !context.getSystemService(PowerManager::class.java).isInteractive)dependency("DEPENDENCY_DEVICE_LOCKED_OR_NOT_INTERACTIVE")
            // Acquire BEFORE changing focus. Busy business Capture is never paused/closed by the probe.
            lease=ProcessRecorders.acquire("instrumentation-timestamp") ?: dependency("DEPENDENCY_RECORDER_BUSY")
            val hold=checkNotNull(lease);hold.modelsReleased() // This probe never constructs any model.
            val cancellation=ProbeControl(hold,meta).also{control=it}
            val intent=Intent().setClassName(context.packageName,NativeTimestampRunner.TARGET)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK).putExtra("nativeTimestampOnly",true)
            activity=instrumentation.startActivitySync(intent) as NativeTimestampForegroundActivity
            val front=checkNotNull(activity)
            val focusDeadline=SystemClock.elapsedRealtime()+5000
            while(!allowed(front) && SystemClock.elapsedRealtime()<focusDeadline)Thread.sleep(20)
            if(!allowed(front))dependency("DEPENDENCY_FOREGROUND_UNAVAILABLE")
            meta.foreground=true;front.cancelNative=cancellation::cancel
            val task=Thread({
                val samples=ShortArray(320)
                try {
                    meta.phase="native_create"
                    val minimum=AudioRecord.getMinBufferSize(16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT)
                    meta.minimumBytes=minimum;check(minimum in 1..32000)
                    val bytes=maxOf(minimum,6400);meta.nativeBytes=bytes
                    if(cancellation.cancelled.get() || !allowed(front))dependency("DEPENDENCY_FOREGROUND_LOST")
                    meta.nativeAttempted=true
                    val native=AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION,16000,AudioFormat.CHANNEL_IN_MONO,
                        AudioFormat.ENCODING_PCM_16BIT,bytes)
                    cancellation.install(native)
                    if(native.state!=AudioRecord.STATE_INITIALIZED)dependency("DEPENDENCY_NATIVE_UNINITIALIZED")
                    meta.actualBufferFrames=native.bufferSizeInFrames
                    check(meta.actualBufferFrames>=bytes/2){"native buffer smaller than requested"}
                    check(native.sampleRate==16000 && native.channelCount==1 && native.audioFormat==AudioFormat.ENCODING_PCM_16BIT){"native format mismatch"}
                    val timestamp=AudioTimestamp()
                    val ledger=NativeReadLedger(bytes/2,CaptureMonotonic::nowMs,SystemClock::elapsedRealtime){
                        val began=System.nanoTime()
                        val result=native.getTimestamp(timestamp,AudioTimestamp.TIMEBASE_MONOTONIC)
                        val ended=System.nanoTime()
                        meta.timestampCalls++;meta.lastApiCode=result;meta.maxApiNs=maxOf(meta.maxApiNs,ended-began)
                        if(result==AudioRecord.SUCCESS){
                            meta.timestampSuccess++
                            if(meta.firstApiSuccessMs<0)meta.firstApiSuccessMs=SystemClock.elapsedRealtime()-meta.startCallMs
                            val age=ended-timestamp.nanoTime;meta.maxStampAgeNs=maxOf(meta.maxStampAgeNs,age);meta.minStampAgeNs=minOf(meta.minStampAgeNs,age)
                            if(meta.lastStampFrames>=0){
                                meta.lastPairDeltaFrames=timestamp.framePosition-meta.lastStampFrames
                                meta.lastPairDeltaNs=timestamp.nanoTime-meta.lastStampNs
                            }
                            meta.lastStampFrames=timestamp.framePosition;meta.lastStampNs=timestamp.nanoTime
                            CaptureStamp(timestamp.framePosition,timestamp.nanoTime)
                        }else{meta.timestampUnavailable++;null}
                    }
                    val prefix=CaptureBootstrap(ledger)
                    cancellation.installStartup(prefix)
                    meta.phase="native_start";meta.startCallMs=SystemClock.elapsedRealtime()
                    cancellation.start();meta.startDurationMs=SystemClock.elapsedRealtime()-meta.startCallMs
                    if(native.recordingState!=AudioRecord.RECORDSTATE_RECORDING)dependency("DEPENDENCY_NATIVE_START_RESTRICTED");meta.started=true
                    meta.phase="timestamp_startup"
                    try {
                        prefix.prepare({target->
                            val n=native.read(target,0,target.size,AudioRecord.READ_NON_BLOCKING)
                            meta.lastReadCode=n
                            if(n==0)meta.emptyReads++ else if(n>0)meta.positiveReads++
                            n
                        },{!cancellation.cancelled.get() && allowed(front)}, {Thread.sleep(5)})
                        meta.samplesRead=ledger.readSamples
                    }finally{meta.samplesRead=ledger.readSamples;prefix.clear()} // No KWS or retained PCM in this instrumentation.
                    var beganReading=-1L;var lastReport=SystemClock.elapsedRealtime()
                    meta.phase="timestamp_startup"
                    while(true){
                        if(cancellation.cancelled.get() || !allowed(front))dependency("DEPENDENCY_FOREGROUND_LOST")
                        if(Build.VERSION.SDK_INT>=29 && native.activeRecordingConfiguration?.isClientSilenced==true)dependency("DEPENDENCY_NATIVE_CLIENT_SILENCED")
                        val room=ledger.remainingMs();meta.minRoomMs=minOf(meta.minRoomMs,room);meta.lastRoomMs=room
                        if(beganReading<0){beganReading=SystemClock.elapsedRealtime();meta.firstLedgerReadyMs=beganReading-meta.startCallMs;meta.phase="continuous_read"}
                        ledger.check()
                        var empty=false
                        try {
                            val count=native.read(samples,0,samples.size,AudioRecord.READ_NON_BLOCKING)
                            meta.lastReadCode=count
                            if(cancellation.cancelled.get() || !allowed(front))dependency("DEPENDENCY_FOREGROUND_LOST")
                            check(count in 0..samples.size)
                            meta.lastSampleBootMs=ledger.read(count);meta.samplesRead=ledger.readSamples
                            if(count==0)meta.emptyReads++ else meta.positiveReads++
                            empty=count==0
                            check(native.recordingState==AudioRecord.RECORDSTATE_RECORDING)
                            meta.runMs=SystemClock.elapsedRealtime()-beganReading
                        }finally{samples.fill(0)}
                        if(meta.runMs>=3000)break
                        if(SystemClock.elapsedRealtime()-lastReport>=1000){emit(meta);lastReport=SystemClock.elapsedRealtime()}
                        if(empty)Thread.sleep(5)
                    }
                    check(meta.positiveReads>=100 && meta.samplesRead>=32000){"insufficient continuous reads"}
                }catch(error:Throwable){
                    meta.failurePhase=meta.phase;meta.nativeExceptionClass=probeFailureClass(error)
                    val classified=when {
                        cancellation.cancelled.get() || !allowed(front)->NativeDependency("DEPENDENCY_FOREGROUND_LOST")
                        error is SecurityException->NativeDependency("DEPENDENCY_NATIVE_PERMISSION_OR_POLICY")
                        else->error
                    }
                    workerFailure.set(classified)
                }
                finally{
                    samples.fill(0);meta.phase="native_cleanup"
                    try{cancellation.release()}catch(error:Throwable){workerCleanupFailure.set(probeFailureClass(error));workerFailure.compareAndSet(null,error)}
                }
            },"native-timestamp-probe")
            worker=task;task.start();task.join(10000)
            if(task.isAlive){cancellation.cancel();throw AssertionError("native probe worker did not finish")}
            meta.workerJoined=true;hold.workerFinished()
            workerFailure.get()?.let{throw it}
            check(meta.stopped && meta.released){"native release unconfirmed"}
            meta.outcome="PASS"
        }catch(error:Throwable){failure=error;if(meta.failurePhase.isEmpty())meta.failurePhase=meta.phase;meta.outcome=if(error is NativeDependency)"NOT_RUN_DEPENDENCY" else "FAIL"
            meta.reason=safeReason(error);meta.exceptionClass=probeFailureClass(error)
        }finally{
            try {
                control?.cancel();worker?.join(1500)
                if(worker?.isAlive!=true){meta.workerJoined=true;lease?.workerFinished()}
                if(worker==null)control?.release()
                control?.joinStop()
                if(activity!=null)instrumentation.runOnMainSync{activity?.finish()}
            }catch(error:Throwable){cleanupClass=probeFailureClass(error)}
            if(cleanupClass.isEmpty())cleanupClass=workerCleanupFailure.get() ?: ""
            meta.dependencyReason=(failure as? NativeDependency)?.code ?: ""
            meta.ownedLeaseComplete=lease?.complete() ?: false
            val decision=decideProbeResult(meta.dependencyReason,
                if(failure!=null && meta.dependencyReason.isEmpty())safeReason(checkNotNull(failure)) else "",
                meta.exceptionClass,cleanupClass,control?.stopFailure?.get() ?: "",
                ProbeReleaseProof(lease!=null,meta.stopped,meta.released,meta.workerJoined,meta.stopTaskJoined,meta.ownedLeaseComplete))
            meta.outcome=decision.outcome;meta.reason=decision.reason;meta.exceptionClass=decision.exceptionClass
            meta.resultJson=decision.json()
            // The host regressions call this same decision's enforce(), not a parallel JUnit policy.
            verdict=decision
            meta.phase="finished";meta.lease=ProcessRecorders.diagnostic();emit(meta)
        }
        checkNotNull(verdict).enforce()
    }
}
