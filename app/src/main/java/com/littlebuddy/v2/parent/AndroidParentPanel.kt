package com.littlebuddy.v2.parent

import android.app.Activity
import android.os.Handler
import android.os.Looper
import java.util.concurrent.Executors

/** Serial IO/KDF worker. System prompts never retain a Grant or an old PIN buffer. */
internal class AndroidParentPanel(private val activity: Activity, leave: () -> Unit,
                                  private val securityRevoked: () -> Unit = {},
                                  private val connectionNotice: () -> String = { "" },
    private val savePublicKey: (ParentPanelModel) -> Unit = {},
    private val pageChanged: (PanelState) -> Unit = {},
    private val configurationSaved: () -> Unit = {}) {
    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor { run -> Thread(run, "v2-parent-io") }
    private lateinit var page: ParentPanelView
    private var closed = false
    private var viewFocused = false
    private val preset = java.util.concurrent.atomic.AtomicReference<DeviceConnectionPreset?>()
    val model = ParentPanelModel({
        preset.set(AndroidDeviceConnectionPreset.load(activity))
        AndroidParentRuntime.load(activity)
    },
        { task -> worker.execute(task) }, { task -> main.post(task) }, { state -> pageChanged(state); page.render(state) }, leave,
        { operation -> beginOwner(operation) }, AndroidParentRuntime::discard, securityRevoked, configurationSaved, directManagement = true)
    private val tick = object : Runnable {
        override fun run() { if (!closed) { model.tick(); main.postDelayed(this, 500) } }
    }
    init {
        AndroidPinDiagnostic.enable()
        page = ParentPanelView(activity, model, connectionNotice = connectionNotice, savePublicKey = { savePublicKey(model) }, connectionPreset = { preset.get() })

    }
    private fun beginOwner(operation: OwnerOperation) { /* No system/PIN owner operations in local mode. */ }
    fun open(force: Boolean = false) {
        if (closed || (viewFocused && !force)) return
        viewFocused = true
        model.open()
        main.removeCallbacks(tick); main.post(tick)
    }
    fun localTouch() { model.localTouch() }
    fun focusLost() { PinDiagnostic.event(PinDiagnostic.Stage.PAGE, PinDiagnostic.Reason.NO_FOCUS); viewFocused = false; model.pause { page.pause() }; main.removeCallbacks(tick) }
    fun pause() { focusLost() }
    fun exit() { model.exit(); page.close(); main.removeCallbacks(tick) }
    fun close() {
        closed = true; model.close(); page.close(); main.removeCallbacks(tick)
        worker.shutdown()
    }
}
