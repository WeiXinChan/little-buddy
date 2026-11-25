package com.littlebuddy.v2.parent

import android.app.Activity
import android.os.Handler
import android.os.Looper
import java.util.concurrent.Executors

/** Serial IO/KDF worker. System prompts never retain a Grant or an old PIN buffer. */
internal class AndroidParentPanel(private val activity: Activity, leave: () -> Unit) {
    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor { run -> Thread(run, "v2-parent-io") }
    private lateinit var page: ParentPanelView
    private lateinit var prompt: AndroidOwnerPrompt
    private var closed = false
    private var viewFocused = false
    val model = ParentPanelModel({ AndroidParentRuntime.load(activity) },
        { task -> worker.execute(task) }, { task -> main.post(task) }, { state -> page.render(state) }, leave,
        { operation -> beginOwner(operation) }, AndroidParentRuntime::discard)
    private val tick = object : Runnable {
        override fun run() { if (!closed) { model.tick(); main.postDelayed(this, 500) } }
    }
    init {
        page = ParentPanelView(activity, model)
        prompt = AndroidOwnerPrompt(activity, { task -> worker.execute(task) }, { if (!closed && activity.hasWindowFocus()) open(force = true) })
    }
    private fun beginOwner(operation: OwnerOperation) { model.pause { page.pause() }; prompt.begin(operation) }
    fun open(force: Boolean = false) {
        if (closed || (viewFocused && !force)) return
        viewFocused = true
        model.open { prompt.take()?.let { (operation, approve) -> model.prepareOwner(operation, approve) } }
        main.removeCallbacks(tick); main.post(tick)
    }
    fun localTouch() { model.localTouch() }
    fun focusLost() { viewFocused = false; model.pause { page.pause() }; main.removeCallbacks(tick) }
    fun pause() { focusLost(); prompt.cancel() }
    fun exit() { model.exit(); prompt.cancel(); page.close(); main.removeCallbacks(tick) }
    fun close() {
        closed = true; model.close(); prompt.cancel(); page.close(); main.removeCallbacks(tick)
        worker.shutdown()
    }
}
