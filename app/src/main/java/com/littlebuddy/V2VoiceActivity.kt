package com.littlebuddy

import android.Manifest
import android.app.Activity
import android.app.KeyguardManager
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.widget.TextView
import android.widget.LinearLayout
import android.widget.Button
import android.widget.EditText
import android.text.InputType
import android.view.View
import com.littlebuddy.v2.EyesView
import com.littlebuddy.v2.EyeScene
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
    private var explicitConnectionStarted = false
    private var releasedRecorder = RecorderProof()
    private var releasedPlayer = PlayerProof()
    private var lastCapturePhase = "NOT_STARTED"
    private var lastCaptureFailure = "NONE"
    internal fun observeDiagnostics(result: (String) -> Unit) { owner.post {
        val recorder = capture?.nativeProof ?: releasedRecorder
        val player = voice?.nativeProof() ?: releasedPlayer
        val failure = if (capture != null) capture?.failedPhase?.name ?: "NONE" else lastCaptureFailure
        result("mode=$releaseState focus=${hasWindowFocus()} keyguard=${getSystemService(KeyguardManager::class.java).isKeyguardLocked} " +
            "permission=${checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED} " +
            "capture_phase=${capture?.phase?.name ?: lastCapturePhase} failed_phase=$failure " +
            "started=${recorder.started} recording=${recorder.recording} frames=${recorder.frames} stopped=${recorder.stopped} released=${recorder.released} " +
            "player_bound=${player.binding != null} head=${player.observedHead}")
    } }
    internal fun observeNative(result: (NativeEvidence) -> Unit) { owner.post {
        result(NativeEvidence(capture?.nativeProof ?: releasedRecorder, voice?.nativeProof() ?: releasedPlayer))
    } }
    internal fun withVoice(action: (VoiceClient) -> Unit) { owner.post { voice?.let(action) } }
    private lateinit var eyes: EyesView
    private val scene = EyeScene()
    // M07 installs only safety-reviewed local catalog entries, never remote URLs.
    internal var pictureResolver: (String) -> android.graphics.Bitmap? = { null }
    private var imageTopic = -1
    internal fun revealImage(effect: String, topic: Int) {
        if (topic < imageTopic || scene.management) return
        val bitmap = pictureResolver(effect) ?: return
        imageTopic = topic
        val ticket = scene.generation
        runOnUiThread { if (scene.accepts(ticket) && topic == imageTopic) eyes.showImage(bitmap) }
    }
    internal fun hideImage() {
        scene.invalidate(); imageTopic = -1
        val ticket = scene.generation
        runOnUiThread { if (ticket == scene.generation) eyes.clearImage() }
    }
    internal val currentMood get() = scene.mood
    internal val isManaging get() = scene.management
    internal val showingImage get() = eyes.showingImage
    internal fun displayEvent(value: String) {
        if (value == "management") return
        val ticket = scene.event(value)
        val mood = scene.mood
        runOnUiThread { if (scene.accepts(ticket)) eyes.mood = mood }
    }
    internal fun manage(entering: Boolean) {
        if (entering) scene.enter() else scene.exit()
        val ticket = scene.generation
        runOnUiThread {
            if (ticket != scene.generation) return@runOnUiThread
            eyes.clearImage()
            if (!entering) { setContentView(eyes); eyes.mood = scene.mood; immersive(); return@runOnUiThread }
            setContentView(LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(48, 32, 48, 32)
                addView(TextView(this@V2VoiceActivity).apply { text = "家长验证"; textSize = 28f })
                addView(EditText(this@V2VoiceActivity).apply {
                    hint = "6 位 PIN"; inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_VARIATION_PASSWORD
                    filters = arrayOf(android.text.InputFilter.LengthFilter(6))
                    isEnabled = false // M08 supplies verification, rate limiting and recovery.
                })
                addView(TextView(this@V2VoiceActivity).apply { text = "家长验证尚未启用，暂不能修改设置。" })
                addView(Button(this@V2VoiceActivity).apply { text = "取消"; setOnClickListener { exitManagement() } })
            })
        }
    }
    internal fun exitManagement() { owner.post {
        capture?.exitManagement(); voice?.management(false); manage(false)
    } }
    private fun immersive() {
        window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_FULLSCREEN or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
            View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        eyes = EyesView(this)
        setContentView(eyes)
        immersive()
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 84)
    }
    /** Called only by an authenticated V2 provisioner, not intent extras/voice. */
    internal fun startVoice(address: String, credential: String) {
        check(hasWindowFocus() && checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
        check(!getSystemService(KeyguardManager::class.java).isKeyguardLocked)
        owner.post {
            voice?.close(); capture?.close()
            check(voice?.quarantined != true && capture?.quarantined != true)
            voice = null; capture = null
            explicitConnectionStarted = true
            releaseState = "active"
            val client = newClient()
            voice = client
            client.connect(address, credential)
            capture = Capture(assets, owner, client, { displayEvent("failure"); stopVoice() }, ::manage).also { it.start() }
        }
    }
    internal fun handleStatus(value: String) {
        if (value == "management") { capture?.enterManagement(); manage(true) } else displayEvent(value)
    }
    private fun newClient() = VoiceClient(owner, ::handleStatus,
        ::hideImage, ::revealImage,
        { displayEvent("failure"); stopVoice() })
    private fun localCommands() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED ||
            getSystemService(KeyguardManager::class.java).isKeyguardLocked) return
        owner.post {
            if (explicitConnectionStarted || voice != null || capture != null || scene.management) return@post
            val client = newClient(); voice = client
            releaseState = "local_kws"
            capture = Capture(assets, owner, client, { displayEvent("failure"); stopVoice() }, ::manage).also { it.start() }
        }
    }
    private fun stopVoice() { owner.post {
        scene.invalidate()
        voice?.close(); voice?.let { releasedPlayer = it.nativeProof() }
        if (voice?.quarantined != true) voice = null
        capture?.close(); capture?.let { releasedRecorder = it.nativeProof; lastCapturePhase = it.phase.name; lastCaptureFailure = it.failedPhase?.name ?: "NONE" }
        // Failed capture release keeps the object, preventing new ownership.
        if (capture?.quarantined != true) capture = null
        releaseState = if (voice == null && capture == null) "released" else "quarantined"
        val ticket = scene.generation
        val mood = scene.mood
        runOnUiThread { if (scene.accepts(ticket)) eyes.mood = mood }
    } }
    override fun onPause() { owner.post { scene.exit(); runOnUiThread { setContentView(eyes); eyes.mood = scene.mood } }; stopVoice(); super.onPause() }
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (!hasFocus) stopVoice() else { immersive(); localCommands() }
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (grantResults.any { it != PackageManager.PERMISSION_GRANTED }) stopVoice() else if (hasWindowFocus()) localCommands()
    }
    override fun onDestroy() {
        stopVoice()
        owner.post { audioThread.quitSafely() }
        super.onDestroy()
    }
}
