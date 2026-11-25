package com.littlebuddy.v2.parent

import android.app.Activity
import android.os.Handler
import android.os.Looper
import java.util.concurrent.Executors

/** One serial IO/KDF worker; delayed UI results are rejected by the model's revision gate. */
internal class AndroidParentPanel(activity: Activity, leave: () -> Unit) {
    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor { run -> Thread(run, "v2-parent-io") }
    private lateinit var page: ParentPanelView
    val model = ParentPanelModel({ AndroidParentRuntime.load(activity) },
        { task -> worker.execute(task) }, { task -> main.post(task) }, { state -> page.render(state) }, leave)
    private val tick = object : Runnable {
        override fun run() { model.tick(); main.postDelayed(this, 500) }
    }
    init { page = ParentPanelView(activity, model) }
    fun open() { model.open(); main.removeCallbacks(tick); main.post(tick) }
    fun localTouch() { model.localTouch() }
    fun pause() { model.pause { page.pause() }; main.removeCallbacks(tick) }
    fun exit() { model.exit(); page.close(); main.removeCallbacks(tick) }
    fun close() {
        model.close(); page.close(); main.removeCallbacks(tick)
        // Existing tasks finish/wipe input; their UI callbacks are stale. No queued auth survives.
        worker.shutdown()
    }
}
