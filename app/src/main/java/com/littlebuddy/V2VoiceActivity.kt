package com.littlebuddy

import android.Manifest
import android.app.Activity
import android.app.KeyguardManager
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.view.MotionEvent
import android.view.WindowManager
import com.littlebuddy.v2.V2EyesView
import com.littlebuddy.v2.parent.AndroidParentPanel
import com.littlebuddy.v2.NativeEvidence
import com.littlebuddy.v2.RecorderProof
import com.littlebuddy.v2.PlayerProof
import com.littlebuddy.v2.Capture
import com.littlebuddy.v2.VoiceClient

/** Isolated V2 host. Endpoint/credential provisioner is deliberately absent until
 * reviewed; tests inject synthetic services. No existing V1 settings are read.
 */
class V2VoiceActivity : Activity() {
    private val audioThread = HandlerThread("v2-audio").apply { start() }
    private val owner = Handler(audioThread.looper)
    @Volatile internal var releaseState: String = "idle"; private set
    private var voice: VoiceClient? = null
    private var capture: Capture? = null
    private var releasedRecorder = RecorderProof()
    private var releasedPlayer = PlayerProof()
    internal fun observeNative(result: (NativeEvidence) -> Unit) { owner.post {
        result(NativeEvidence(capture?.nativeProof ?: releasedRecorder, voice?.nativeProof() ?: releasedPlayer))
    } }
    internal fun withVoice(action: (VoiceClient) -> Unit) { owner.post { voice?.let(action) } }
    private var panel: AndroidParentPanel? = null
    private var managementRequested = false
    private var managementVisible = false
    private var foreground = false
    private var managementRevision = 0L
    private fun eyes() { setContentView(V2EyesView(this) { requestParentManagement() }) }
    private fun leaveManagement() {
        managementRevision++; managementRequested = false; managementVisible = false
        panel?.close(); panel = null
        eyes() // Standby only; never resumes a prior child session or starts a recorder.
    }
    /** Frozen local entry seam for a future reviewed voice-management adapter.
     * Current main has no safe pause/PCM-watermark bridge: an active audio session refuses
     * entry instead of closing/rebuilding it and pretending management retention was proved.
     */
    internal fun requestParentManagement() {
        if (!foreground || !hasWindowFocus() || managementRequested || managementVisible) return
        if (getSystemService(KeyguardManager::class.java).isKeyguardLocked) return
        managementRequested = true
        val ticket = ++managementRevision
        owner.post {
            val quiet = voice == null && capture == null && releaseState != "quarantined"
            runOnUiThread {
                if (ticket != managementRevision || !foreground || !hasWindowFocus()) return@runOnUiThread
                managementRequested = false
                if (!quiet) return@runOnUiThread // OPEN: M06 management pause/retention contract.
                managementVisible = true
                panel = AndroidParentPanel(this) { leaveManagement() }.also { it.open() }
            }
        }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        eyes()
        if (Build.VERSION.SDK_INT >= 33) {
            onBackInvokedDispatcher.registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT) {
                if (managementVisible) panel?.exit() else finish()
            }
        }
    }
    /** Called only by an authenticated V2 provisioner, not intent extras/voice. */
    internal fun startVoice(address: String, credential: String) {
        check(!managementRequested && !managementVisible)
        check(hasWindowFocus() && checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
        check(!getSystemService(KeyguardManager::class.java).isKeyguardLocked)
        owner.post {
            check(voice == null && capture == null)
            releaseState = "active"
            val client = VoiceClient(owner, { _ -> }, {}, { _, _ -> }, { stopVoice() })
            voice = client
            client.connect(address, credential)
            capture = Capture(assets, owner, client) { stopVoice() }.also { it.start() }
        }
    }
    private fun stopVoice() { owner.post {
        voice?.close(); voice?.let { releasedPlayer = it.nativeProof() }
        if (voice?.quarantined != true) voice = null
        capture?.close(); capture?.let { releasedRecorder = it.nativeProof }
        // Failed capture release keeps the object, preventing new ownership.
        if (capture?.quarantined != true) capture = null
        releaseState = if (voice == null && capture == null) "released" else "quarantined"
    } }
    override fun onResume() {
        super.onResume(); foreground = true
        if (managementVisible && hasWindowFocus()) panel?.open()
    }
    override fun onPause() {
        foreground = false; managementRevision++; managementRequested = false
        panel?.pause() // Synchronous atomic revoke BEFORE audio-owner work or framework pause.
        stopVoice(); super.onPause()
    }
    override fun dispatchTouchEvent(event: MotionEvent): Boolean {
        if (event.actionMasked == MotionEvent.ACTION_DOWN) panel?.localTouch()
        return super.dispatchTouchEvent(event)
    }
    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (managementVisible) panel?.exit() else super.onBackPressed()
    }
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (!hasFocus) {
            managementRevision++; managementRequested = false
            panel?.pause(); stopVoice()
        } else if (foreground && managementVisible) panel?.open()
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (grantResults.any { it != PackageManager.PERMISSION_GRANTED }) stopVoice()
    }
    override fun onDestroy() {
        foreground = false; managementRevision++; managementRequested = false
        panel?.close(); panel = null
        stopVoice()
        owner.post { audioThread.quitSafely() }
        super.onDestroy()
    }
}
