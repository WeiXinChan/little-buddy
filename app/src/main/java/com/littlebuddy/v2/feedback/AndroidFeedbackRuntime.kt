package com.littlebuddy.v2.feedback

import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.ComponentName
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.io.File

/** Local monotonic continuity only, not a trusted server clock. No real provider is enabled. */
internal class AndroidFeedbackClock : FeedbackClock {
    private val wall = System.currentTimeMillis()
    private val elapsed = SystemClock.elapsedRealtime()
    override fun now(): Long? {
        val delta = SystemClock.elapsedRealtime() - elapsed
        return if (delta < 0) null else maxOf(System.currentTimeMillis(), wall + delta)
    }
}
/** Reuse a matching persisted job. Re-registering from onStartJob could cancel the active run. */
internal class AndroidFeedbackJobSchedule(context: Context) : FeedbackJobSchedule {
    private val app = context.applicationContext
    override fun ensure(): Boolean {
        val scheduler = app.getSystemService(JobScheduler::class.java) ?: return false
        val component = ComponentName(app, FeedbackSweepService::class.java)
        return FeedbackJobRegistration({
            val current = scheduler.getPendingJob(AndroidFeedbackRuntime.JOB_ID)
            current != null && current.service == component && current.isPersisted && current.isPeriodic &&
                current.intervalMillis == PERIOD && current.networkType == JobInfo.NETWORK_TYPE_NONE &&
                !current.isRequireCharging && !current.isRequireDeviceIdle &&
                !current.isRequireBatteryNotLow && !current.isRequireStorageNotLow
        }, {
            val request = JobInfo.Builder(AndroidFeedbackRuntime.JOB_ID, component)
                .setPersisted(true).setPeriodic(PERIOD).build()
            scheduler.schedule(request) == JobScheduler.RESULT_SUCCESS
        }).ensure()
    }
    companion object { const val PERIOD = 15 * 60_000L }
}
internal object AndroidFeedbackRuntime {
    const val JOB_ID = 0x4D09
    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadScheduledExecutor { work -> Thread(work, "v2-feedback-local") }
    private var instance: FeedbackEngine? = null
    private var maintenance: FeedbackMaintenance? = null
    private var owner: FeedbackCoreOwner? = null // retained for process lifetime, all access on worker
    val jobScheduled: Boolean get() = maintenance?.jobScheduled == true
    @Synchronized fun start(context: Context) {
        if (instance == null) open(context) else maintenance!!.start()
    }
    @Synchronized fun open(context: Context): FeedbackEngine {
        instance?.let { return it }
        val app = context.applicationContext
        val queue = FeedbackQueue { action -> worker.execute(action) }
        val next = FeedbackEngine(queue, FeedbackQueue { action -> main.post(action) }, { authorizer ->
            check(Looper.myLooper() != Looper.getMainLooper())
            val store = owner ?: FeedbackCoreOwner(File(app.noBackupFilesDir, "m09-feedback.owner"),
                { AndroidFeedbackVault.open(app) }, AndroidFeedbackClock()).also { owner = it }
            store.open(authorizer)
        })
        val cleanup = FeedbackMaintenance(queue, next, AndroidFeedbackJobSchedule(app), FeedbackPeriodic { tick ->
            worker.scheduleAtFixedRate({ tick() }, 60, 60, TimeUnit.SECONDS)
        })
        instance = next; maintenance = cleanup
        cleanup.start()
        return next
    }
    @Synchronized fun request(context: Context, done: (Boolean) -> Unit) {
        open(context); maintenance!!.request(done)
    }
    fun jobRuns(context: Context, finish: (JobParameters, Boolean) -> Unit): FeedbackJobRuns<JobParameters> {
        open(context)
        return FeedbackJobRuns(maintenance!!, FeedbackQueue { action -> main.post(action) }, finish)
    }
}

/** Only the system can bind (manifest BIND_JOB_SERVICE); receives no material or credentials. */
class FeedbackSweepService : JobService() {
    private val runs by lazy { AndroidFeedbackRuntime.jobRuns(this) { params, retry -> jobFinished(params, retry) } }
    override fun onStartJob(params: JobParameters): Boolean {
        if (params.jobId != AndroidFeedbackRuntime.JOB_ID) return false
        runs.start(params)
        return true
    }
    override fun onStopJob(params: JobParameters): Boolean {
        if (params.jobId == AndroidFeedbackRuntime.JOB_ID) runs.stop(params)
        return true // queued sweep remains safe; it has deletion-only system authority
    }
}
