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
import com.littlebuddy.v2.LifecycleGate
import com.littlebuddy.v2.StopTimeline
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import com.littlebuddy.v2.Capture
import com.littlebuddy.v2.VoiceClient

/** Isolated V2 host. Endpoint/credential provisioner is deliberately absent until
 * reviewed; tests inject synthetic services. No existing V1 settings are read.
 */
class V2VoiceActivity : Activity() {
    private val audioThread = HandlerThread("v2-audio").apply { start() }
    private val owner = Handler(audioThread.looper)
    @Volatile internal var releaseState: String = "idle"; private set
    @Volatile private var voice: VoiceClient? = null
    @Volatile private var capture: Capture? = null
    internal var transportOverride: ((okhttp3.Request,okhttp3.WebSocketListener)->okhttp3.WebSocket)? = null
    internal var afterEligible: ()->Unit = {}
    private val life=LifecycleGate()
    private val timeline=StopTimeline(SystemClock::elapsedRealtime)
    internal fun immediateRecorder()=capture?.nativeProof ?: releasedRecorder
    internal fun mark(name: String) { timeline.add(name,life.state.generation,immediateRecorder(),capture?.phase?.name ?: lastCapturePhase) }
    internal fun timelineJson(): String = JSONArray(timeline.snapshot().map {
        JSONObject().put("ms",it.ms).put("event",it.event).put("generation",it.generation)
            .put("session",it.session).put("frames",it.frames).put("recording",it.recording)
            .put("stopped",it.stopped).put("released",it.released).put("phase",it.phase)
    }).toString()
    internal val resumed get()=life.state.resumed
    internal val eyesFrame get()=eyes.drawSerial
    internal fun requestEyesFrame() { eyes.postInvalidateOnAnimation() }
    private fun eligible(ticket: Long)=life.allows(ticket) &&
        checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED &&
        !getSystemService(KeyguardManager::class.java).isKeyguardLocked
    private var explicitConnectionStarted = false
    @Volatile private var releasedRecorder = RecorderProof()
    private var releasedPlayer = PlayerProof()
    private var lastCapturePhase = "NOT_STARTED"
    private var lastCaptureFailure = "NONE"
    internal fun observeDiagnostics(result: (String) -> Unit) { owner.post {
        val recorder = capture?.nativeProof ?: releasedRecorder
        val player = voice?.nativeProof() ?: releasedPlayer
        val failure = if (capture != null) capture?.failedPhase?.name ?: "NONE" else lastCaptureFailure
        result("resumed=${life.state.resumed} generation=${life.state.generation} mode=$releaseState focus=${hasWindowFocus()} keyguard=${getSystemService(KeyguardManager::class.java).isKeyguardLocked} " +
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
        val ticket=life.state.generation
        owner.post {
            if(!eligible(ticket)) { mark("STALE_CONNECT_REJECTED"); return@post }
            afterEligible()
            if(!eligible(ticket)) { mark("STALE_CONNECT_REJECTED"); return@post }
            voice?.close(); capture?.close()
            if(voice?.quarantined==true || capture?.quarantined==true) { mark("RECONNECT_QUARANTINED"); return@post }
            voice = null; capture = null
            explicitConnectionStarted = true
            releaseState = "active"
            val client = newClient()
            voice = client
            if(!installCapture(client,ticket))return@post
            if(eligible(ticket))client.connect(address,credential) else { capture?.requestStop(); stopVoice() }
        }
    }
    private fun makeCapture(client: VoiceClient,ticket: Long): Capture {
        lateinit var created: Capture
        created=Capture(assets,owner,client,
            { if(capture===created) { displayEvent("failure"); stopVoice() } },
            { entering -> if(capture===created && life.allows(ticket))manage(entering) },
            { life.allows(ticket) },
            { event,proof,phase -> timeline.add(event,ticket,proof,phase) },
            disposed = { owner.post {
                mark("DISPOSE_CONSUME")
                if(capture===created && !created.quarantined && eligible(life.state.generation))localCommands()
            } })
        return created
    }
    private fun installCapture(client: VoiceClient,ticket: Long): Boolean {
        val created=makeCapture(client,ticket); capture=created
        if(!created.start()) {
            created.requestStop(); client.close()
            if(capture===created)capture=null
            if(voice===client)voice=null
            releaseState="released"; mark("STALE_CAPTURE_START_REJECTED")
            return false
        }
        return true
    }
    internal fun handleStatus(value: String) {
        if (value == "management") { capture?.enterManagement(); manage(true) } else displayEvent(value)
    }
    private fun newClient(): VoiceClient { val ticket=life.state.generation; return VoiceClient(owner, { if(life.allows(ticket))handleStatus(it) },
        ::hideImage, ::revealImage,
        { displayEvent("failure"); stopVoice() }, socketFactory=transportOverride) }
    private fun localCommands(retryUntil: Long=SystemClock.elapsedRealtime()+1500) {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED ||
            getSystemService(KeyguardManager::class.java).isKeyguardLocked) return
        val ticket=life.state.generation
        owner.post {
            if(!eligible(ticket)) { mark("STALE_LOCAL_START_REJECTED"); return@post }
            afterEligible()
            if(!eligible(ticket)) { mark("STALE_LOCAL_START_REJECTED"); return@post }
            val held=capture
            if(held?.closing==true) {
                if(held.workerDone && !held.quarantined && held.nativeProof.released) { releasedRecorder=held.nativeProof; capture=null }
                else { if(SystemClock.elapsedRealtime()<retryUntil) owner.postDelayed({if(eligible(ticket))localCommands(retryUntil)},50)
                    else mark("DISPOSAL_WAIT_EXPIRED")
                    return@post
                }
            }
            if (explicitConnectionStarted || voice != null || capture != null || scene.management) return@post
            val client = newClient(); voice = client
            releaseState = "local_kws"
            if(!installCapture(client,ticket) && eligible(ticket) && SystemClock.elapsedRealtime()<retryUntil)owner.postDelayed({if(eligible(ticket))localCommands(retryUntil)},50)
        }
    }
    private fun stopVoice() {
        val stopping=capture; val stoppingVoice=voice
        mark("STOP_ENQUEUE")
        stopping?.requestStop() // before owner queue or model destruction
        owner.post {
        mark("STOP_CONSUME")
        if(capture!==stopping || voice!==stoppingVoice) { mark("STALE_STOP_REJECTED"); return@post }
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
        mark("STOP_FINISH")
        if(stopping!=null && stopping.quarantined && stopping.nativeProof.released) {
            val generation=life.state.generation; val deadline=SystemClock.elapsedRealtime()+1500
            fun reap() {
                if(capture!==stopping || !eligible(generation))return
                if(stopping.workerDone && !stopping.quarantined) { releasedRecorder=stopping.nativeProof; capture=null; localCommands() }
                else if(SystemClock.elapsedRealtime()<deadline)owner.postDelayed({reap()},50)
                else mark("DISPOSAL_WAIT_EXPIRED")
            }
            owner.postDelayed({reap()},50)
        }
    } }
    override fun onResume() { super.onResume(); life.resume(); mark("LIFE_RESUME"); if(hasWindowFocus()) { life.focus(true); localCommands() } }
    override fun onPause() { life.pause(); mark("LIFE_PAUSE"); owner.post { scene.exit(); runOnUiThread { setContentView(eyes); eyes.mood = scene.mood } }; stopVoice(); super.onPause() }
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        life.focus(hasFocus); mark(if(hasFocus)"FOCUS_GAIN" else "FOCUS_LOSS")
        if (!hasFocus) stopVoice() else { immersive(); localCommands() }
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (grantResults.any { it != PackageManager.PERMISSION_GRANTED }) stopVoice() else if (hasWindowFocus()) localCommands()
    }
    override fun onDestroy() {
        life.destroy(); mark("LIFE_DESTROY")
        stopVoice()
        owner.post { audioThread.quitSafely() }
        super.onDestroy()
    }
}
