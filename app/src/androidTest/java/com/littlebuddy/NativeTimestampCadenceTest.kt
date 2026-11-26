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
import com.littlebuddy.v2.ProcessRecorders
import com.littlebuddy.v2.RecorderLease
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Test
import java.util.concurrent.atomic.AtomicReference

/** One bounded metadata observation. NO production admission, models, audio consumer or retries. */
class NativeTimestampCadenceTest {
    private val instrumentation get()=InstrumentationRegistry.getInstrumentation()
    private val context get()=instrumentation.targetContext
    private fun dependency(code:String):Nothing=throw NativeDependency(code)
    private fun allowed(front:NativeTimestampForegroundActivity)=front.active && front.focused &&
        context.checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED &&
        !context.getSystemService(KeyguardManager::class.java).isKeyguardLocked &&
        context.getSystemService(PowerManager::class.java).isInteractive
    private fun reason(e:Throwable?)=when(e){null->"";is NativeDependency->e.code;is CadenceStopped->e.code;else->"CADENCE_NATIVE_OR_HARNESS_EXCEPTION"}
    private fun emit(r:CadenceObservation,m:ProbeMetadata,d:ProbeDecision) {
        // No instrumentation IO while capture is running; never traverse worker-owned rows before join.
        val trace=JSONArray()
        if(m.workerJoined)for(t in r.rows)trace.put(JSONObject().apply {
            put("i",t.index);put("f",t.frames);put("ns",t.stampNs)
            put("mono_before",t.apiBeforeNs);put("mono_after",t.apiAfterNs)
            put("boot_before",t.bootBeforeNs);put("boot_after",t.bootAfterNs);put("read",t.readSamples)
            put("df",t.adjacentFrames);put("dn",t.adjacentNs)
            put("first_df",t.cumulativeFrames);put("first_dn",t.cumulativeNs)
            put("window_df",t.windowFrames);put("window_dn",t.windowNs)
            put("old_rate_reject",t.legacyRateRejected);put("flags",t.flags);put("late",t.late)
        })
        instrumentation.sendStatus(7,Bundle().apply {
            putInt("sdk",Build.VERSION.SDK_INT);putInt("target_version_code",m.targetVersion)
            putBoolean("foreground_at_preflight",m.foreground);putBoolean("record_audio_permission_at_preflight",m.permission)
            putBoolean("locked_at_preflight",m.locked)
            putInt("minimum_bytes",m.minimumBytes);putInt("native_bytes",m.nativeBytes);putInt("actual_buffer_frames",m.actualBufferFrames)
            putBoolean("native_attempted",m.nativeAttempted);putBoolean("recording_started",m.started);putLong("start_duration_ms",m.startDurationMs)
            putBoolean("native_stopped",m.stopped);putBoolean("native_released",m.released)
            putBoolean("worker_joined",m.workerJoined);putBoolean("stop_task_joined",m.stopTaskJoined);putBoolean("owned_lease_complete",m.ownedLeaseComplete)
            putString("recorder_lease_post_cleanup",ProcessRecorders.diagnostic())
            putString("native_exception_class",m.nativeExceptionClass);putString("stop_exception_class",m.stopExceptionClass)
            putString("v2_cadence_scope","DIAGNOSTIC_ONLY_NOT_PRODUCTION_PASS")
            putString("v2_cadence_outcome",if(d.outcome=="PASS")"ONE_SESSION_OBSERVATION_ONLY" else d.outcome)
            putString("reason",d.reason);putString("dependency_reason",d.dependencyReason)
            putBoolean("production_pass",false);putBoolean("production_gate_executed",false)
            putBoolean("physical_continuity_certified",false);putBoolean("audio_saved",false);putBoolean("audio_uploaded",false)
            putInt("native_session_requests",1);putBoolean("trace_withheld_worker_alive",!m.workerJoined)
            if(m.workerJoined){
                putString("terminal",r.terminal);putLong("elapsed_ns",r.elapsedNs)
                putInt("read_calls",r.readCalls);putLong("read_samples",r.samples);putInt("empty_reads",r.emptyReads)
                putInt("api_calls",r.apiCalls);putInt("successes",r.successful)
                putString("api_codes",r.codes.entries.joinToString(","){"${it.key}:${it.value}"})
                putLong("first_success_elapsed_ns_from_call",r.firstSuccessElapsedNs);putLong("max_api_ns",r.maxApiNs)
                putLong("max_read_ns",r.maxReadNs);putLong("max_stamp_age_ns",r.maxAgeNs)
                putInt("old_rate_rejections",r.rateRejections);putInt("anomaly_rows",r.anomalies);putInt("late_api_calls",r.lateCalls)
                putString("trace_json",trace.toString());putInt("trace_rows",r.rows.size)
            }
        })
    }
    @SuppressLint("MissingPermission")
    private fun session(front:NativeTimestampForegroundActivity,hold:RecorderLease) {
        val meta=ProbeMetadata();val result=CadenceObservation();val control=ProbeControl(hold,meta)
        val failure=AtomicReference<Throwable?>();val cleanup=AtomicReference<String?>(null)
        meta.foreground=front.active && front.focused
        meta.permission=context.checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED
        meta.locked=context.getSystemService(KeyguardManager::class.java).isKeyguardLocked
        meta.targetVersion=context.packageManager.getPackageInfo(context.packageName,0).versionCode
        hold.modelsReleased();front.cancelNative=control::cancel
        val task=Thread({try {
            if(!allowed(front) || control.cancelled.get())dependency("DEPENDENCY_FOREGROUND_LOST")
            meta.minimumBytes=AudioRecord.getMinBufferSize(16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT)
            meta.nativeBytes=6400
            if(meta.minimumBytes !in 1..6400)dependency("DEPENDENCY_FIXED_NATIVE_BUFFER_UNAVAILABLE")
            meta.nativeAttempted=true
            val native=AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION,16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT,6400)
            control.install(native)
            if(native.state!=AudioRecord.STATE_INITIALIZED)dependency("DEPENDENCY_NATIVE_UNINITIALIZED")
            meta.actualBufferFrames=native.bufferSizeInFrames
            if(meta.actualBufferFrames!=3200)dependency("DEPENDENCY_NATIVE_BUFFER_CHANGED")
            check(native.sampleRate==16000 && native.channelCount==1 && native.audioFormat==AudioFormat.ENCODING_PCM_16BIT)
            val timestamp=AudioTimestamp()
            val port=object:CadencePort {
                override fun monoNs()=System.nanoTime()
                override fun bootNs()=SystemClock.elapsedRealtimeNanos()
                override fun allowed():Boolean {
                    if(Build.VERSION.SDK_INT>=29 && native.activeRecordingConfiguration?.isClientSilenced==true)
                        dependency("DEPENDENCY_NATIVE_CLIENT_SILENCED")
                    return !control.cancelled.get() && allowed(front)
                }
                override fun read(samples:ShortArray,count:Int)=native.read(samples,0,count,AudioRecord.READ_NON_BLOCKING)
                override fun timestamp():StartupApiSample {
                    val code=native.getTimestamp(timestamp,AudioTimestamp.TIMEBASE_MONOTONIC)
                    return if(code==AudioRecord.SUCCESS)StartupApiSample(code,timestamp.framePosition,timestamp.nanoTime) else StartupApiSample(code)
                }
                override fun pause(){Thread.sleep(5)}
            }
            val origin=CadenceDiagnostic.origin(port) // Budget includes the startRecording call.
            meta.phase="cadence_native_start";meta.startCallMs=SystemClock.elapsedRealtime();control.start()
            meta.startDurationMs=SystemClock.elapsedRealtime()-meta.startCallMs
            if(native.recordingState!=AudioRecord.RECORDSTATE_RECORDING)dependency("DEPENDENCY_NATIVE_START_RESTRICTED")
            meta.started=true;meta.phase="cadence_observation"
            CadenceDiagnostic.run(port,result,origin)
        }catch(e:Throwable){meta.nativeExceptionClass=probeFailureClass(e)
            failure.set(if(e is SecurityException)NativeDependency("DEPENDENCY_NATIVE_PERMISSION_OR_POLICY") else e)
        }finally{try{control.release()}catch(e:Throwable){cleanup.set(probeFailureClass(e))}}},"native-timestamp-cadence")
        var harness:Throwable?=null
        try{task.start();task.join(5500);if(task.isAlive){control.cancel();throw AssertionError("CADENCE_WORKER_DEADLINE")}}
        catch(e:Throwable){harness=e}
        finally {
            try{control.cancel();task.join(1500);meta.workerJoined=!task.isAlive
                if(meta.workerJoined)hold.workerFinished();control.joinStop()
            }catch(e:Throwable){cleanup.compareAndSet(null,probeFailureClass(e))}
            meta.ownedLeaseComplete=hold.complete()
            val error=harness ?: failure.get()
            val decision=decideProbeResult((error as? NativeDependency)?.code ?: "",reason(error),error?.let(::probeFailureClass) ?: "",
                cleanup.get() ?: "",control.stopFailure.get() ?: "",
                ProbeReleaseProof(true,meta.stopped,meta.released,meta.workerJoined,meta.stopTaskJoined,meta.ownedLeaseComplete))
            emit(result,meta,decision);decision.enforce()
        }
    }
    @Test fun observeOneBoundedCadence(){
        if(instrumentation !is NativeTimestampRunner)dependency("DEPENDENCY_EXPLICIT_NATIVE_RUNNER_REQUIRED")
        if(context.packageName!="com.littlebuddy.sim.v2" || context.applicationContext.javaClass!=Application::class.java)
            dependency("DEPENDENCY_TARGET_APPLICATION_NOT_ISOLATED")
        if(context.packageManager.getPackageInfo(context.packageName,0).versionCode!=21)dependency("DEPENDENCY_RC7_CODE21_REQUIRED")
        if(context.checkSelfPermission(Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED)dependency("DEPENDENCY_RECORD_AUDIO_PERMISSION")
        if(context.getSystemService(KeyguardManager::class.java).isKeyguardLocked || !context.getSystemService(PowerManager::class.java).isInteractive)
            dependency("DEPENDENCY_DEVICE_LOCKED_OR_NOT_INTERACTIVE")
        val hold=ProcessRecorders.acquire("instrumentation-cadence") ?: dependency("DEPENDENCY_RECORDER_BUSY")
        var used=false;var front:NativeTimestampForegroundActivity?=null
        try {
            val intent=Intent().setClassName(context.packageName,NativeTimestampRunner.TARGET).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK).putExtra("nativeTimestampOnly",true)
            front=instrumentation.startActivitySync(intent) as NativeTimestampForegroundActivity
            val activity=checkNotNull(front);val limit=SystemClock.elapsedRealtime()+5000
            while(!allowed(activity) && SystemClock.elapsedRealtime()<limit)Thread.sleep(20)
            if(!allowed(activity))dependency("DEPENDENCY_FOREGROUND_UNAVAILABLE")
            used=true;session(activity,hold)
        }finally {
            if(!used){hold.nativeReleased();hold.modelsReleased();hold.workerFinished()}
            front?.cancelNative=null
            if(front!=null)try{instrumentation.runOnMainSync{front?.finish()}}
                catch(e:Throwable){throw AssertionError("CADENCE_FOREGROUND_CLEANUP_FAILED; class="+probeFailureClass(e))}
        }
    }
}
