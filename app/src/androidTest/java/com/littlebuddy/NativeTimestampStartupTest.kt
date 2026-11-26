package com.littlebuddy

import android.Manifest
import android.annotation.SuppressLint
import android.app.Application
import android.app.KeyguardManager
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
import androidx.test.platform.app.InstrumentationRegistry
import com.littlebuddy.v2.CaptureMonotonic
import com.littlebuddy.v2.ProcessRecorders
import com.littlebuddy.v2.RecorderLease
import org.junit.Test
import java.util.concurrent.atomic.AtomicReference

/** At most two TEST ONLY sessions. No production authorization, audio sink or bootstrap change. */
class NativeTimestampStartupTest {
    private var sessionRequests=0
    private val instrumentation get()=InstrumentationRegistry.getInstrumentation()
    private val context get()=instrumentation.targetContext
    private fun dependency(code:String):Nothing=throw NativeDependency(code)
    private fun allowed(front:NativeTimestampForegroundActivity)=front.active && front.focused &&
        context.checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED &&
        !context.getSystemService(KeyguardManager::class.java).isKeyguardLocked &&
        context.getSystemService(PowerManager::class.java).isInteractive
    private fun emit(result:StartupObservation,meta:ProbeMetadata,index:Int,outcome:String,reason:String,dependency:String="") {
        instrumentation.sendStatus(7,Bundle().apply {
            putString("v2_startup_scope","DIAGNOSTIC_ONLY_NOT_PRODUCTION_PASS")
            putString("v2_startup_outcome",outcome);putString("reason",reason);putString("dependency_reason",dependency)
            putInt("session_index",index);putString("mode",result.mode.name);putString("terminal",result.terminal)
            putLong("window_limit_ms",StartupDiagnostic.WINDOW_MS);putLong("elapsed_ms",result.elapsedMs)
            putInt("api_calls",result.apiCalls);putString("api_codes",result.codes.entries.joinToString(","){"${it.key}:${it.value}"})
            putInt("read_calls",result.readCalls);putLong("samples_read_and_discarded",result.readSamples);putInt("last_read_code",result.lastReadCode)
            putLong("first_success_ms_after_start_return",result.firstSuccessMs)
            putLong("first_success_ms_after_start_call",if(result.firstSuccessMs<0)-1 else meta.startDurationMs+result.firstSuccessMs)
            putLong("first_success_frames",result.firstSuccessFrames);putLong("first_success_ns",result.firstSuccessNs)
            putLong("first_well_formed_ms",result.firstWellFormedMs);putInt("invalid_pairs",result.invalidPairs)
            putInt("position_regressions",result.positionRegressions);putInt("time_regressions",result.timeRegressions)
            putLong("last_frames",result.lastFrames);putLong("last_ns",result.lastNs);putLong("max_stamp_age_ns",result.maxAgeNs)
            putLong("max_api_ms",result.maxApiMs);putInt("minimum_bytes",meta.minimumBytes);putInt("native_bytes",meta.nativeBytes)
            putInt("actual_buffer_frames",meta.actualBufferFrames);putLong("start_duration_ms",meta.startDurationMs)
            putBoolean("recording_started",meta.started);putBoolean("native_stopped",meta.stopped);putBoolean("native_released",meta.released)
            putBoolean("worker_joined",meta.workerJoined);putBoolean("stop_task_joined",meta.stopTaskJoined)
            putBoolean("owned_lease_complete",meta.ownedLeaseComplete);putString("stop_exception_class",meta.stopExceptionClass)
            putString("native_exception_class",meta.nativeExceptionClass);putString("recorder_lease",ProcessRecorders.diagnostic())
            putBoolean("audio_retained",false);putBoolean("audio_uploaded",false);putBoolean("production_continuity_evaluated",false)
        })
    }
    private fun reason(error:Throwable?):String=when(error){
        null->""
        is NativeDependency->error.code
        is StartupDiagnosticStopped->error.code
        else->"DIAG_NATIVE_OR_HARNESS_EXCEPTION"
    }
    @SuppressLint("MissingPermission")
    private fun session(front:NativeTimestampForegroundActivity,hold:RecorderLease,mode:StartupMode,index:Int):StartupObservation {
        val meta=ProbeMetadata();val result=StartupObservation(mode);val control=ProbeControl(hold,meta)
        val failure=AtomicReference<Throwable?>();val cleanup=AtomicReference<String?>(null)
        hold.modelsReleased() // No model/effect/credential/provider is constructed by this diagnostic.
        front.cancelNative=control::cancel
        val task=Thread({try{
            if(!allowed(front) || control.cancelled.get())dependency("DEPENDENCY_FOREGROUND_LOST")
            val minimum=AudioRecord.getMinBufferSize(16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT)
            meta.minimumBytes=minimum;meta.nativeBytes=6400
            if(minimum !in 1..6400)dependency("DEPENDENCY_FIXED_NATIVE_BUFFER_UNAVAILABLE")
            meta.nativeAttempted=true
            val native=AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION,16000,AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,6400)
            control.install(native)
            if(native.state!=AudioRecord.STATE_INITIALIZED)dependency("DEPENDENCY_NATIVE_UNINITIALIZED")
            meta.actualBufferFrames=native.bufferSizeInFrames
            if(meta.actualBufferFrames!=3200)dependency("DEPENDENCY_NATIVE_BUFFER_CHANGED")
            check(native.sampleRate==16000 && native.channelCount==1 && native.audioFormat==AudioFormat.ENCODING_PCM_16BIT)
            meta.startCallMs=SystemClock.elapsedRealtime();control.start()
            meta.startDurationMs=SystemClock.elapsedRealtime()-meta.startCallMs
            if(native.recordingState!=AudioRecord.RECORDSTATE_RECORDING)dependency("DEPENDENCY_NATIVE_START_RESTRICTED")
            meta.started=true
            val timestamp=AudioTimestamp()
            StartupDiagnostic.run(object:StartupPort {
                override fun nowMs()=CaptureMonotonic.nowMs()
                override fun allowed():Boolean {
                    if(Build.VERSION.SDK_INT>=29 && native.activeRecordingConfiguration?.isClientSilenced==true)
                        dependency("DEPENDENCY_NATIVE_CLIENT_SILENCED")
                    return !control.cancelled.get() && allowed(front)
                }
                override fun read(samples:ShortArray,count:Int)=native.read(samples,0,count,AudioRecord.READ_NON_BLOCKING)
                override fun timestamp():StartupApiSample {
                    val code=native.getTimestamp(timestamp,AudioTimestamp.TIMEBASE_MONOTONIC)
                    return if(code==AudioRecord.SUCCESS)StartupApiSample(code,timestamp.framePosition,timestamp.nanoTime)
                        else StartupApiSample(code)
                }
                override fun pause(ms:Long){Thread.sleep(ms)}
            },result)
        }catch(error:Throwable){meta.nativeExceptionClass=probeFailureClass(error)
            failure.set(if(error is SecurityException)NativeDependency("DEPENDENCY_NATIVE_PERMISSION_OR_POLICY") else error)
        }finally{try{control.release()}catch(error:Throwable){cleanup.set(probeFailureClass(error))}}},"timestamp-startup-session-$index")
        var harness:Throwable?=null
        try{task.start();task.join(2500)
            if(task.isAlive){control.cancel();throw AssertionError("DIAG_WORKER_DEADLINE")}
        }catch(error:Throwable){harness=error}
        finally{
            try{control.cancel();task.join(1500);meta.workerJoined=!task.isAlive
                if(meta.workerJoined)hold.workerFinished();control.joinStop()
            }catch(error:Throwable){cleanup.compareAndSet(null,probeFailureClass(error))}
            meta.ownedLeaseComplete=hold.complete()
            val original=harness ?: failure.get()
            val decision=decideProbeResult((original as? NativeDependency)?.code ?: "",reason(original),
                original?.let(::probeFailureClass) ?: "",cleanup.get() ?: "",control.stopFailure.get() ?: "",
                ProbeReleaseProof(true,meta.stopped,meta.released,meta.workerJoined,meta.stopTaskJoined,meta.ownedLeaseComplete))
            emit(result,meta,index,if(decision.outcome=="PASS")"SESSION_COMPLETE_OBSERVATION_ONLY" else decision.outcome,decision.reason,decision.dependencyReason)
            decision.enforce() // Cleanup failure always dominates a dependency; no second session on failure.
        }
        return result
    }
    private fun comparison():String {
        if(instrumentation !is NativeTimestampRunner)dependency("DEPENDENCY_EXPLICIT_NATIVE_RUNNER_REQUIRED")
        if(context.packageName!="com.littlebuddy.sim.v2" || context.applicationContext.javaClass!=Application::class.java)
            dependency("DEPENDENCY_TARGET_APPLICATION_NOT_ISOLATED")
        if(context.checkSelfPermission(Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED)dependency("DEPENDENCY_RECORD_AUDIO_PERMISSION")
        if(context.getSystemService(KeyguardManager::class.java).isKeyguardLocked || !context.getSystemService(PowerManager::class.java).isInteractive)
            dependency("DEPENDENCY_DEVICE_LOCKED_OR_NOT_INTERACTIVE")
        val first=ProcessRecorders.acquire("startup-diagnostic-poll") ?: dependency("DEPENDENCY_RECORDER_BUSY")
        var activity:NativeTimestampForegroundActivity?=null;var firstUsed=false
        try{
            val intent=Intent().setClassName(context.packageName,NativeTimestampRunner.TARGET).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                .putExtra("nativeTimestampOnly",true)
            activity=instrumentation.startActivitySync(intent) as NativeTimestampForegroundActivity
            val front=checkNotNull(activity);val deadline=SystemClock.elapsedRealtime()+5000
            while(!allowed(front) && SystemClock.elapsedRealtime()<deadline)Thread.sleep(20)
            if(!allowed(front))dependency("DEPENDENCY_FOREGROUND_UNAVAILABLE")
            firstUsed=true;sessionRequests++
            val a=session(front,first,StartupMode.TIMESTAMP_ONLY,1)
            if(!allowed(front))dependency("DEPENDENCY_FOREGROUND_LOST")
            val second=ProcessRecorders.acquire("startup-diagnostic-read") ?: dependency("DEPENDENCY_RECORDER_BUSY")
            sessionRequests++
            val b=session(front,second,StartupMode.READ_THEN_TIMESTAMP,2)
            return StartupDiagnostic.interpretation(a,b)
        }finally{
            if(!firstUsed){first.nativeReleased();first.modelsReleased();first.workerFinished()}
            activity?.cancelNative=null
            if(activity!=null)try{instrumentation.runOnMainSync{activity?.finish()}}
                catch(error:Throwable){throw AssertionError("DIAG_FOREGROUND_CLEANUP_FAILED; class="+probeFailureClass(error))}
        }
    }
    @Test fun compareTimestampStartup(){
        var failure:Throwable?=null;var interpretation="NOT_OBSERVED"
        try{interpretation=comparison()}catch(error:Throwable){failure=error}
        val outcome=when(failure){null->"TWO_SESSIONS_COMPLETE_OBSERVATION_ONLY";is NativeDependency->"NOT_RUN_DEPENDENCY";else->"FAIL"}
        instrumentation.sendStatus(7,Bundle().apply {
            putString("v2_startup_scope","DIAGNOSTIC_ONLY_NOT_PRODUCTION_PASS");putString("v2_startup_outcome",outcome)
            putString("interpretation",interpretation);putInt("session_requests",sessionRequests)
            putString("reason",reason(failure));putString("exception_class",failure?.let(::probeFailureClass) ?: "")
            putBoolean("production_probe_pass",false);putBoolean("production_changed",false)
        })
        failure?.let {if(it is NativeDependency)throw it;throw AssertionError("startup diagnostic failed; reason="+reason(it)+"; class="+probeFailureClass(it))}
    }
}
