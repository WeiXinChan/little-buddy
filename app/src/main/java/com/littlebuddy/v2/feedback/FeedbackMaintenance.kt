package com.littlebuddy.v2.feedback

import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

internal fun interface FeedbackJobSchedule { fun ensure(): Boolean }
internal class FeedbackJobRegistration(private val matches: () -> Boolean,
    private val register: () -> Boolean) : FeedbackJobSchedule {
    override fun ensure() = matches() || register()
}
internal fun interface FeedbackPeriodic { fun install(tick: () -> Unit) }

/** The same worker runs registration and the actual engine. No parent/Grant is needed. */
internal class FeedbackMaintenance(private val worker: FeedbackQueue, private val engine: FeedbackEngine,
    private val schedule: FeedbackJobSchedule, private val periodic: FeedbackPeriodic) {
    private val periodicStarted = AtomicBoolean(false)
    private val gate = Any()
    private var running = false
    private val listeners = mutableListOf<(Boolean) -> Unit>()
    @Volatile var jobScheduled = false; private set
    @Volatile var lastSweepSucceeded: Boolean? = null; private set
    fun start() {
        if (periodicStarted.compareAndSet(false, true)) {
            try { periodic.install { request() } }
            catch (_: Exception) { periodicStarted.set(false) }
        }
        request() // cold start compensates for missed/late OS execution; no UI/preview/PIN
    }
    fun request(done: (Boolean) -> Unit = {}) {
        synchronized(gate) {
            listeners.add(done)
            if (running) return
            running = true
        }
        try {
            worker.post { jobScheduled = try { schedule.ensure() } catch (_: Exception) { false } }
            // Capture the engine page/version NOW, before registration/worker IO and later edits.
            engine.sweep(::finish)
        } catch (_: Exception) { finish(false) }
    }
    private fun finish(success: Boolean) {
        lastSweepSucceeded = success
        val callbacks = synchronized(gate) {
            running = false
            listeners.toList().also { listeners.clear() }
        }
        callbacks.forEach { try { it(success) } catch (_: Exception) { /* bounded result only */ } }
    }
}

/** A stopped/replaced OS execution cannot finish a newer execution or revive its callback. */
internal class FeedbackJobRuns<T : Any>(private val maintenance: FeedbackMaintenance,
    private val ui: FeedbackQueue, private val finish: (T, Boolean) -> Unit) {
    private class Run<T>(val params: T)
    private val active = AtomicReference<Run<T>?>()
    fun start(params: T) {
        val run = Run(params); active.set(run)
        maintenance.request { success ->
            ui.post { if (active.compareAndSet(run, null)) finish(params, !success) }
        }
    }
    fun stop(params: T) {
        val run = active.get() ?: return
        if (run.params === params) active.compareAndSet(run, null)
    }
}
