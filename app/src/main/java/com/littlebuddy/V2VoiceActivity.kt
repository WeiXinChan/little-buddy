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
import android.widget.Toast
import com.littlebuddy.v2.*
import com.littlebuddy.v2.parent.*
import java.util.concurrent.Executors

/** V2-only host. Existing issued credentials stay in the encrypted parent domain, never Intent extras. */
class V2VoiceActivity : Activity() {
    private val audioThread = HandlerThread("v2-audio").apply { start() }
    private val owner = Handler(audioThread.looper)
    private val configurationWorker = Executors.newSingleThreadExecutor()
    @Volatile internal var releaseState: String = "idle"; private set
    private var voice: VoiceClient? = null
    private var capture: Capture? = null
    private var releasedRecorder = RecorderProof()
    private var releasedPlayer = PlayerProof()
    private var execution = ParentPlaybackSettings()
    private var budget: PlaybackBudget? = null
    private var panel: AndroidParentPanel? = null
    private var help: LocalHelpOutput? = null
    private var managementRequested = false
    private var managementVisible = false
    private var helpVisible = false
    @Volatile private var foreground = false
    @Volatile private var managementRevision = 0L
    private var permissionRequested = false
    private fun eyes() { setContentView(V2EyesView(this) { requestParentManagement() }.also {
        it.onLocalHelp = { showLocalHelp() }
    }) }
    internal fun observeNative(result: (NativeEvidence) -> Unit) { owner.post {
        result(NativeEvidence(capture?.nativeProof ?: releasedRecorder, voice?.nativeProof() ?: releasedPlayer))
    } }
    internal fun withVoice(action: (VoiceClient) -> Unit) { owner.post { voice?.let(action) } }
    private fun leaveManagement() {
        managementRevision++; managementRequested = false; managementVisible = false
        panel?.close(); panel = null; eyes(); resumeConfigured()
    }
    /** Voice or hidden corner can request the page; neither grants configuration rights.
     * This batch ends the child transport before management, rather than claiming a retained audio session.
     */
    internal fun requestParentManagement() {
        if (!foreground || !hasWindowFocus() || managementRequested || managementVisible) return
        if (getSystemService(KeyguardManager::class.java).isKeyguardLocked) return
        helpVisible = false; help?.stop(); managementRequested = true
        val ticket = ++managementRevision
        releaseAudio { quiet ->
            if (ticket != managementRevision || !foreground || !hasWindowFocus()) return@releaseAudio
            managementRequested = false
            if (!quiet) { showLocalHelp(); return@releaseAudio }
            managementVisible = true
            panel = AndroidParentPanel(this) { leaveManagement() }.also { it.open() }
        }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        help = LocalHelpOutput(this) { helpVisible = false; eyes(); resumeConfigured() }
        eyes()
        if (Build.VERSION.SDK_INT >= 33) onBackInvokedDispatcher.registerOnBackInvokedCallback(
            android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT) { back() }
    }
    private fun resumeConfigured() {
        if (!foreground || !hasWindowFocus() || managementVisible || managementRequested || helpVisible) return
        val ticket = managementRevision
        configurationWorker.execute {
            val configuration = runCatching { AndroidParentRuntime.load(this).childConfiguration() }.getOrNull()
            runOnUiThread {
                if (ticket != managementRevision || !foreground || !hasWindowFocus() || managementVisible || managementRequested || helpVisible) return@runOnUiThread
                if (configuration != null) execution = configuration.playback
                val connection = configuration?.connection ?: return@runOnUiThread
                if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                    if (!permissionRequested) { permissionRequested = true; requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 804) }
                    return@runOnUiThread
                }
                execution = configuration.playback
                startVoice(connection.address, connection.credential)
            }
        }
    }
    /** Internal native regression seam; production calls this only after encrypted provisioning. */
    internal fun startVoice(address: String, credential: String) {
        check(!managementRequested && !managementVisible && !helpVisible)
        check(hasWindowFocus() && checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
        check(!getSystemService(KeyguardManager::class.java).isKeyguardLocked)
        val ticket = managementRevision; val settings = execution
        owner.post {
            if (ticket != managementRevision || !foreground || voice != null || capture != null || releaseState == "quarantined") return@post
            releaseState = "active"; budget = PlaybackBudget(android.os.SystemClock::elapsedRealtime, settings.durationSeconds)
            val client = VoiceClient(owner, { status ->
                if (status == "listening" && voice?.isAwake == true) budget?.begin()
            }, {}, { _, _ -> }, { runOnUiThread { if (ticket == managementRevision) showLocalHelp() } },
                playbackSettings = settings,
                localHelp = { runOnUiThread { if (ticket == managementRevision) showLocalHelp() } },
                management = { runOnUiThread { if (ticket == managementRevision) requestParentManagement() } },
                permitted = { foreground && ticket == managementRevision })
            voice = client
            try { client.connect(address, credential)
                capture = Capture(assets, owner, client, allowed = { foreground && ticket == managementRevision }) { runOnUiThread { if (ticket == managementRevision) showLocalHelp() } }.also { it.start() }
                owner.postDelayed(durationLimit, 250)
            } catch (_: Exception) { runOnUiThread { if (ticket == managementRevision) showLocalHelp() } }
        }
    }
    private val durationLimit = object : Runnable {
        override fun run() {
            if (voice == null) return
            if (budget?.expired() == true) {
                runOnUiThread {
                    val ticket = ++managementRevision
                    releaseAudio { quiet -> if (quiet && ticket == managementRevision && foreground && hasWindowFocus()) {
                        Toast.makeText(this@V2VoiceActivity, "这一轮先休息一下，再玩时重新唤醒。", Toast.LENGTH_LONG).show()
                        eyes(); resumeConfigured()
                    } }
                }
            } else owner.postDelayed(this, 250)
        }
    }
    private fun releaseAudio(done: (Boolean) -> Unit = {}) { owner.post {
        owner.removeCallbacks(durationLimit)
        voice?.close(); voice?.let { releasedPlayer = it.nativeProof() }
        if (voice?.quarantined != true) voice = null
        capture?.close(); capture?.let { releasedRecorder = it.nativeProof }
        if (capture?.quarantined != true) capture = null
        budget = null
        val quiet = voice == null && capture == null
        releaseState = if (quiet) "released" else "quarantined"
        runOnUiThread { done(quiet) }
    } }
    private fun stopVoice() = releaseAudio()
    private fun showLocalHelp() {
        if (!foreground || !hasWindowFocus() || managementVisible || managementRequested || helpVisible) return
        helpVisible = true; val ticket = ++managementRevision
        help?.show(ParentPlaybackSettings(volume = 0), audible = false, released = false)
        releaseAudio { quiet ->
            configurationWorker.execute {
                val settings = runCatching { AndroidParentRuntime.helpSettings(this) }.getOrNull()
                runOnUiThread {
                    if (ticket == managementRevision && foreground && hasWindowFocus() && helpVisible)
                        help?.show(settings ?: ParentPlaybackSettings(volume = 0), quiet && settings != null, quiet)
                }
            }
        }
    }
    override fun onResume() {
        super.onResume(); foreground = true
        if (managementVisible && hasWindowFocus()) panel?.open()
        else if (!managementVisible && !helpVisible) { eyes(); resumeConfigured() }
    }
    override fun onPause() {
        foreground = false; managementRevision++; managementRequested = false
        panel?.pause(); helpVisible = false; help?.stop(); stopVoice(); super.onPause()
    }
    override fun dispatchTouchEvent(event: MotionEvent): Boolean {
        if (event.actionMasked == MotionEvent.ACTION_DOWN) panel?.localTouch()
        return super.dispatchTouchEvent(event)
    }
    private fun back() {
        if (managementVisible) panel?.exit()
        else if (helpVisible) { helpVisible = false; help?.stop(); eyes(); resumeConfigured() }
        else finish()
    }
    @Deprecated("Deprecated in Java") override fun onBackPressed() { back() }
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (!hasFocus) {
            managementRevision++; managementRequested = false
            panel?.focusLost(); helpVisible = false; help?.stop(); stopVoice()
        } else if (foreground) {
            if (managementVisible) panel?.open()
            else if (!helpVisible) { eyes(); resumeConfigured() }
        }
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (grantResults.any { it != PackageManager.PERMISSION_GRANTED }) stopVoice() else resumeConfigured()
    }
    override fun onDestroy() {
        foreground = false; managementRevision++; managementRequested = false
        panel?.close(); panel = null; help?.close(); help = null
        stopVoice(); owner.post { audioThread.quitSafely() }; configurationWorker.shutdown()
        super.onDestroy()
    }
}
