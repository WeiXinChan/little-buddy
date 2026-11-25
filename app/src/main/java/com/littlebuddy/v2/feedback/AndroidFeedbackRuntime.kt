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
import java.util.concurrent.atomic.AtomicReference

/** Local monotonic continuity only, not a trusted server clock. No real provider is enabled. */
internal class AndroidFeedbackClock : FeedbackClock {
    private val wall = System.currentTimeMillis()
    private val elapsed = SystemClock.elapsedRealtime()
    override fun now(): Long? {
        val delta = SystemClock.elapsedRealtime() - elapsed
        return if (delta < 0) null else maxOf(System.currentTimeMillis(), wall + delta)
    }
}
internal object AndroidFeedbackRuntime {
    const val JOB_ID = 0x4D09
    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadScheduledExecutor { work -> Thread(work, "v2-feedback-local") }
    private var instance: FeedbackEngine? = null
    @Volatile var jobScheduled = false; private set
    @Synchronized fun open(context: Context): FeedbackEngine {
        instance?.let { return it }
        val app = context.applicationContext
        val next = FeedbackEngine(FeedbackQueue { action -> worker.execute(action) },
            FeedbackQueue { action -> main.post(action) }, { authorizer ->
                check(Looper.myLooper() != Looper.getMainLooper())
                FeedbackCore(AndroidFeedbackVault.open(app), AndroidFeedbackClock(), authorizer)
            })
        instance = next
        // Worker exists for process lifetime; closing a parent page never cancels system deletion.
        worker.scheduleAtFixedRate({ next.sweep() }, 0, 60, TimeUnit.SECONDS)
        jobScheduled = try {
            val request = JobInfo.Builder(JOB_ID, ComponentName(app, FeedbackSweepService::class.java))
                .setPersisted(true).setPeriodic(15 * 60_000L).build()
            app.getSystemService(JobScheduler::class.java).schedule(request) == JobScheduler.RESULT_SUCCESS
        } catch (_: Exception) { false }
        return next
    }
}

/** Only the system can bind (manifest BIND_JOB_SERVICE); receives no material or credentials. */
class FeedbackSweepService : JobService() {
    private val active = AtomicReference<JobParameters?>()
    override fun onStartJob(params: JobParameters): Boolean {
        if (params.jobId != AndroidFeedbackRuntime.JOB_ID) return false
        active.set(params)
        AndroidFeedbackRuntime.open(this).sweep { success ->
            Handler(Looper.getMainLooper()).post {
                if (active.compareAndSet(params, null)) jobFinished(params, !success)
            }
        }
        return true
    }
    override fun onStopJob(params: JobParameters): Boolean {
        active.compareAndSet(params, null)
        return true // queued sweep remains safe; it has deletion-only system authority
    }
}
