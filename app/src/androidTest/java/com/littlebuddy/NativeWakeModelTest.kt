package com.littlebuddy

import android.app.Activity
import android.app.Application
import android.app.KeyguardManager
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.PowerManager
import android.os.Process
import android.os.SystemClock
import android.view.WindowManager
import android.widget.TextView
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.AndroidJUnitRunner
import com.littlebuddy.v2.ProcessRecorders
import com.littlebuddy.v2.RecorderLease
import org.junit.Test
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Separate runner: no changes to the native timestamp/default runner or its allowlists. */
class NativeWakeModelRunner:AndroidJUnitRunner() {
    override fun newApplication(loader:ClassLoader,name:String,context:Context):Application=
        super.newApplication(loader,Application::class.java.name,context)
    override fun onCreate(arguments:Bundle?){
        val args=Bundle(arguments ?: Bundle())
        require(WakeProbeSelection.permitsKeys(args.keySet()) && WakeProbeSelection.permits(args.getString("class"),args.getString("nativeWakeModelProbe"),
            args.getString("businessIdlePreflight"),args.getString("knownWakeFixtures"))){"exact wake probe and actual host idle preflight required"}
        args.putString("disableAnalytics","true");super.onCreate(args)
    }
    override fun newActivity(loader:ClassLoader,name:String,intent:Intent):Activity {
        check(name==NativeTimestampRunner.TARGET && intent.getBooleanExtra("wakeModelOnly",false)){"business Activity forbidden"}
        return NativeWakeForegroundActivity()
    }
}
class NativeWakeForegroundActivity:Activity() {
    @Volatile var active=false;private set
    @Volatile var focused=false;private set
    @Volatile var cancel:(()->Unit)?=null
    override fun onCreate(state:Bundle?){super.onCreate(state)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        setContentView(TextView(this).apply{text="本地合成模型验证\n不采集或播放声音，不连接业务。";isSaveEnabled=false;textSize=22f})}
    override fun onResume(){super.onResume();active=true}
    override fun onPause(){active=false;cancel?.invoke();super.onPause()}
    override fun onWindowFocusChanged(value:Boolean){super.onWindowFocusChanged(value);focused=value;if(!value)cancel?.invoke()}
    override fun onDestroy(){active=false;cancel?.invoke();super.onDestroy()}
}
class NativeWakeModelTest {
    private val instrumentation get()=InstrumentationRegistry.getInstrumentation()
    private val context get()=instrumentation.targetContext
    private fun allowed(front:NativeWakeForegroundActivity)=front.active && front.focused &&
        context.getSystemService(PowerManager::class.java).isInteractive &&
        !context.getSystemService(KeyguardManager::class.java).isKeyguardLocked
    private fun dependency(code:String):Nothing=throw WakeProbeDependency(code)

    @Test fun packagedProductionModelOnFrozenFixtures(){
        val invocationStart=SystemClock.elapsedRealtime();val processCpuStart=Process.getElapsedCpuTime()
        val cancelled=AtomicBoolean(false);val installed=AtomicReference<WakeFixtureKernel?>()
        fun cancel(){cancelled.set(true);installed.get()?.clear()}
        var lease:RecorderLease?=null;var worker:Thread?=null;var front:NativeWakeForegroundActivity?=null
        val workerFailure=AtomicReference<Throwable?>();var failure:Throwable?=null
        var cleanupClass="";var joined=false;var targetVersion=0
        var preflight=false;var modelsConfirmed=false
        var result:ProbeDecision?=null
        try {
            if(instrumentation !is NativeWakeModelRunner)dependency("DEPENDENCY_EXPLICIT_WAKE_RUNNER_REQUIRED")
            if(context.applicationContext.javaClass!=Application::class.java)dependency("DEPENDENCY_WAKE_APPLICATION_NOT_ISOLATED")
            check(context.packageName=="com.littlebuddy.sim.v2")
            targetVersion=context.packageManager.getPackageInfo(context.packageName,0).versionCode
            lease=ProcessRecorders.acquire("instrumentation-wake-model") ?: dependency("DEPENDENCY_RECORDER_BUSY")
            // No AudioRecord or recorder stop task is ever allocated. Models/worker remain unproven.
            val hold=checkNotNull(lease);hold.nativeReleased()
            val intent=Intent().setClassName(context.packageName,NativeTimestampRunner.TARGET)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK).putExtra("wakeModelOnly",true)
            front=instrumentation.startActivitySync(intent) as NativeWakeForegroundActivity
            val activity=checkNotNull(front);val deadline=SystemClock.elapsedRealtime()+5000
            while(!allowed(activity) && SystemClock.elapsedRealtime()<deadline)Thread.sleep(20)
            if(!allowed(activity))dependency("DEPENDENCY_WAKE_FOREGROUND_UNAVAILABLE")
            preflight=true;activity.cancel=::cancel
            val task=Thread({
                var kernel:WakeFixtureKernel?=null
                try {
                    val budget=WakeProbeBudget(SystemClock::elapsedRealtime,Process::getElapsedCpuTime)
                    kernel=WakeFixtureKernel(budget,{!cancelled.get() && allowed(activity)},
                        {context.assets.open(it)},{instrumentation.context.assets.open(it)},
                        {decodeAllowed->
                            // Actual target class/AAR/ONNX. No controlled keyword or test-defined shadow.
                            val production=SherpaWake(context.assets,decodeAllowed)
                            object:WakeProbeEngine {
                                override fun accept(samples:ShortArray,count:Int)=production.accept(samples,count)
                                override fun close()=production.close()
                            }
                        })
                    installed.set(kernel);if(cancelled.get())kernel.clear()
                    kernel.run()
                }catch(error:Throwable){
                    val classified=try {classifyWakeFailure(error){cancelled.get() || !allowed(activity)}}
                        catch(classificationError:Throwable){WakeProbeViolation("WAKE_CLASSIFICATION_FAILED")}
                    workerFailure.set(classified)
                }
                finally {
                    kernel?.clear()
                    // Any failed constructor/close keeps the lease quarantined, including partial JNI init.
                    if(kernel!=null && kernel.attempted==kernel.closed){hold.modelsReleased()}
                }
            },"wake-model-fixture-probe")
            worker=task;task.start();task.join(65_000)
            if(task.isAlive){cancel();throw WakeProbeViolation("WAKE_WORKER_TIMEOUT")}
            joined=true;hold.workerFinished()
            workerFailure.get()?.let{throw it}
            val kernel=checkNotNull(installed.get())
            wakeRequire(kernel.hashesVerified && kernel.results.size==4 && kernel.closed==4,"WAKE_MODEL_COMPLETION")
        }catch(error:Throwable){failure=error}
        finally {
            cancel()
            try {
                worker?.join(1500)
                if(worker?.isAlive!=true){joined=true;lease?.workerFinished()
                    val kernel=installed.get()
                    modelsConfirmed=kernel==null || kernel.attempted==kernel.closed
                    if(modelsConfirmed)lease?.modelsReleased()
                }
                if(front!=null)instrumentation.runOnMainSync{front?.finish()}
            }catch(error:Throwable){cleanupClass=probeFailureClass(error)}
            val kernel=installed.get()
            if(cleanupClass.isEmpty())cleanupClass=kernel?.cleanupClass ?: ""
            val dep=(failure as? WakeProbeDependency)?.code ?: ""
            val originalReason=when(val error=failure){null->"";is WakeProbeDependency->"";is WakeProbeViolation->error.code;else->"WAKE_MODEL_PROBE_FAILED"}
            val decision=decideProbeResult(dep,originalReason,failure?.let(::probeFailureClass) ?: "",cleanupClass,"",
                ProbeReleaseProof(lease!=null,true,true,joined,true,lease?.complete()==true && modelsConfirmed))
            result=decision
            // Never read the mutable case list until real worker join. Only aggregate metadata, no input/output text.
            val meta=Bundle().apply {
                putString("wake_probe_phase","finished");putString("wake_probe_outcome",decision.outcome)
                putString("wake_probe_result_json",decision.json());putString("wake_probe_reason",decision.reason)
                putString("dependency_reason",dep);putString("exception_class",decision.exceptionClass)
                putString("cleanup_exception_class",cleanupClass);putInt("target_version_code",targetVersion)
                putBoolean("preflight_foreground",preflight);putBoolean("microphone_allocated",false)
                putBoolean("native_recorder_not_applicable",true);putBoolean("stop_task_not_applicable",true)
                putBoolean("worker_joined",joined);putBoolean("model_release_confirmed",modelsConfirmed)
                putBoolean("owned_lease_complete",lease?.complete()==true);putString("process_lease",ProcessRecorders.diagnostic())
                putString("last_phase",kernel?.phase ?: "preflight")
                putInt("models_attempted",kernel?.attempted ?: 0);putInt("models_constructed",kernel?.constructed ?: 0)
                putInt("models_closed",kernel?.closed ?: 0);putLong("samples_offered",kernel?.totalFed ?: 0)
                putBoolean("hashes_verified",kernel?.hashesVerified==true)
                putLong("last_guard_wall_ms",kernel?.budget?.wallMs ?: 0);putLong("last_guard_process_cpu_ms",kernel?.budget?.cpuMs ?: 0)
                putLong("probe_elapsed_ms",SystemClock.elapsedRealtime()-invocationStart);putLong("process_total_cpu_ms",Process.getElapsedCpuTime()-processCpuStart)
                putLong("wall_budget_ms",WakeProbeBudget.WALL_MS);putLong("cpu_budget_ms",WakeProbeBudget.CPU_MS)
                putLong("sample_budget",WakeProbeBudget.SAMPLE_CAP)
                if(joined && kernel!=null){
                    putString("last_case_id",kernel.currentCase);putInt("last_case_offered",kernel.currentOffered)
                    putInt("last_case_hits",kernel.currentHits);putLong("last_case_raw_tail",kernel.currentTail ?: -1)
                    for((i,case) in kernel.results.withIndex()){
                        putString("case_${i}_id",case.id);putInt("case_${i}_fixture_samples",case.fixtureSamples)
                        putInt("case_${i}_fed_samples",case.fed);putInt("case_${i}_hits",case.hits)
                        putLong("case_${i}_tail",case.tail ?: -1);putLong("case_${i}_wall_ms",case.wallMs)
                    }
                    val digestPrefix=if(kernel.hashesVerified)"verified" else "expected_unverified"
                    for((i,asset) in FrozenWakeInputs.fixtures.withIndex())putString("${digestPrefix}_fixture_${i}_sha256",asset.sha256)
                    for((i,asset) in FrozenWakeInputs.models.withIndex())putString("${digestPrefix}_model_${i}_sha256",asset.sha256)
                }
            }
            instrumentation.sendStatus(7,meta)
        }
        checkNotNull(result).enforce()
    }
}
