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
    internal fun captureWorkerEvidence()=capture?.workerEvidence() ?: "no_capture"
    internal val captureWorkerDone get()=capture?.let{it.workerDone && it.leaseReturned} ?: true
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
    private class ConnectionIntent(val id:Long,val generation:Long,val address:String,val credential:String)
    private val connectionSequence=java.util.concurrent.atomic.AtomicLong()
    private val pendingConnection=com.littlebuddy.v2.PendingConnection<ConnectionIntent>()
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
            "player_bound=${player.binding != null} head=${player.observedHead} ${captureWorkerEvidence()}")
    } }
    internal fun observeNative(result: (NativeEvidence) -> Unit) { owner.post {
        result(NativeEvidence(capture?.nativeProof ?: releasedRecorder, voice?.nativeProof() ?: releasedPlayer))
    } }
    internal fun withVoice(action: (VoiceClient) -> Unit) { owner.post { voice?.let(action) } }
    private val promptSequence=java.util.concurrent.atomic.AtomicLong()
    @Volatile private var promptNative:com.littlebuddy.v2.AndroidTrack?=null
    private var promptOutput:com.littlebuddy.v2.ManagedPromptPlayback?=null
    private fun stopManagementPrompt(){
        promptSequence.incrementAndGet()
        try{promptNative?.mute()}catch(_:Exception){mark("LOCAL_PROMPT_MUTE_FAILED")}
        owner.post{promptOutput?.let{it.cancel();timeline.add("LOCAL_PROMPT_CANCELLED",life.state.generation,immediateRecorder(),"head=${it.proof.observedHead} stop=${it.proof.stop}")};if(promptOutput?.quarantined!=true){promptOutput=null;promptNative=null}}
    }
    private fun playManagementPrompt(text:String,valid:()->Boolean,done:(Boolean)->Unit){
        val sequence=promptSequence.incrementAndGet();val ticket=life.state.generation
        owner.post {
            promptOutput?.cancel()
            if(promptOutput?.quarantined==true || !eligible(ticket) || !scene.management || !valid()){done(false);return@post}
            var routeSeen=false
            promptNative=null
            val manager=getSystemService(android.media.AudioManager::class.java)
            val cue=com.littlebuddy.v2.ManagedPromptPlayback(
                {com.littlebuddy.v2.AndroidTrack(owner){stopManagementPrompt()}.also{promptNative=it}},
                SystemClock::elapsedRealtime,
                {val native=promptNative;val routed=native==null || native.head==0L || native.hasRoute;if(native!=null && native.head>0 && routed)routeSeen=true;manager.getStreamVolume(android.media.AudioManager.STREAM_MUSIC)>0 && !manager.isStreamMute(android.media.AudioManager.STREAM_MUSIC) && routed})
            promptOutput=cue
            try {
                val path=if(text.startsWith("要退出"))"management/confirm_prompt.wav" else "management/stay_prompt.wav"
                val bytes=assets.open(path).use{it.readBytes()}
                val b=java.nio.ByteBuffer.wrap(bytes).order(java.nio.ByteOrder.LITTLE_ENDIAN)
                check(bytes.size>44 && String(bytes,0,4)=="RIFF" && String(bytes,36,4)=="data" && b.getInt(24)==24000 && b.getShort(22).toInt()==1 && b.getShort(34).toInt()==16)
                val pcm=ShortArray((bytes.size-44)/2);b.position(44);b.asShortBuffer().get(pcm)
                cue.begin(pcm);mark("LOCAL_PROMPT_BEGIN")
            }catch(_:Exception){cue.cancel()}
            fun pump(){
                if(sequence!=promptSequence.get() || !eligible(ticket) || !scene.management || !valid()){cue.cancel();done(false);return}
                cue.tick()
                val result=cue.result
                if(result==null){owner.postDelayed({pump()},10);return}
                timeline.add(if(result)"LOCAL_PROMPT_NATIVE_COMPLETE" else "LOCAL_PROMPT_FAILED",ticket,immediateRecorder(),"head=${cue.proof.observedHead} stop=${cue.proof.stop} audibleRoute=$routeSeen")
                if(!cue.quarantined){promptOutput=null;promptNative=null}
                if(result){owner.postDelayed({done(sequence==promptSequence.get() && eligible(ticket) && scene.management && valid())},200)}else done(false)
            }
            pump()
        }
    }
    @Volatile internal var beforeManagementPrompt: (((()->Unit))->Unit)?=null
    @Volatile internal var beforeCaptureDispose:()->Unit={}
    @Volatile internal var beforeManagementCommand: (String?)->Unit={}
    @Volatile internal var managementPromptSerial=0L;private set
    private fun showManagementPrompt(text:String,valid:()->Boolean,ack:(Boolean)->Unit){val hook=beforeManagementPrompt;if(hook!=null)hook{drawManagementPrompt(text,valid,ack)} else drawManagementPrompt(text,valid,ack)}
    private fun drawManagementPrompt(text:String,valid:()->Boolean,ack:(Boolean)->Unit){runOnUiThread{
        val view=managementPromptView ?: return@runOnUiThread
        val generation=scene.generation
        if(!scene.management || !valid()){ack(false);return@runOnUiThread}
        view.text=text
        val listener=object:android.view.ViewTreeObserver.OnDrawListener {var sent=false
            override fun onDraw(){if(sent)return;sent=true;view.post{if(view.viewTreeObserver.isAlive)view.viewTreeObserver.removeOnDrawListener(this);if(scene.management && scene.generation==generation && managementPromptView===view && valid()){managementPromptSerial++;playManagementPrompt(text,valid,ack)}}}
        }
        view.viewTreeObserver.addOnDrawListener(listener);view.invalidate()
    }}
    private var managementPromptView: TextView?=null
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
                addView(TextView(this@V2VoiceActivity).apply { managementPromptView=this; text="" })
                addView(Button(this@V2VoiceActivity).apply { text = "取消"; setOnClickListener { exitManagement() } })
            })
        }
    }
    internal fun exitManagement() { stopManagementPrompt();owner.post {
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
        val ticket=life.state.generation;val id=connectionSequence.incrementAndGet()
        owner.post {
            if(id!=connectionSequence.get() || !eligible(ticket)){mark("STALE_CONNECT_REJECTED");return@post}
            afterEligible()
            if(id!=connectionSequence.get() || !eligible(ticket)){mark("STALE_CONNECT_REJECTED");return@post}
            pendingConnection.offer(id,ticket,ConnectionIntent(id,ticket,address,credential))
            voice?.close();voice?.let{releasedPlayer=it.nativeProof()}
            if(voice?.quarantined!=true)voice=null
            capture?.requestStop();capture?.close()
            resumeConnection()
        }
    }
    private fun resumeConnection() {
        if(!pendingConnection.present)return
        val held=capture
        if(voice?.quarantined==true || held?.resourceFailed==true){pendingConnection.invalidate();mark("RECONNECT_RESOURCE_FAULT");return}
        val ready=held==null || (held.workerDone && held.nativeProof.released && held.leaseReturned && !held.quarantined)
        val intent=pendingConnection.take(connectionSequence.get(),::eligible,ready)
        if(intent==null){if(pendingConnection.present){releaseState="waiting_disposal";mark("CONNECTION_PENDING_DISPOSAL")};return}
        held?.let{releasedRecorder=it.nativeProof};capture=null
        val client=newClient();voice=client;releaseState="active"
        if(!installCapture(client,intent.generation))return
        if(intent.id==connectionSequence.get() && eligible(intent.generation))client.connect(intent.address,intent.credential) else stopVoice()
    }
    private fun makeCapture(client: VoiceClient,ticket: Long): Capture {
        lateinit var created: Capture
        created=Capture(assets,owner,client,
            { if(capture===created) { displayEvent("failure"); stopVoice() } },
            { entering -> if(capture===created && life.allows(ticket))manage(entering) },
            { life.allows(ticket) },
            { event,proof,phase -> timeline.add(event,ticket,proof,phase) },
            hooks=com.littlebuddy.v2.CaptureHooks(beforeDispose={beforeCaptureDispose()},beforeCommandDecision={beforeManagementCommand(it)}),
            disposed = { owner.post {
                mark("DISPOSE_CONSUME")
                if(capture===created && created.workerDone && created.nativeProof.released && created.leaseReturned && !created.quarantined){
                    voice?.close();voice?.let{releasedPlayer=it.nativeProof()};if(voice?.quarantined!=true)voice=null
                    releasedRecorder=created.nativeProof;capture=null;releaseState="released"
                    if(pendingConnection.present)resumeConnection() else if(eligible(life.state.generation))localCommands()
                }
            } }, managementPrompt=::showManagementPrompt)
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
    private fun localCommands() {
        val ticket=life.state.generation
        owner.post {
            if(!eligible(ticket)){mark("STALE_LOCAL_START_REJECTED");return@post}
            afterEligible()
            if(!eligible(ticket)){mark("STALE_LOCAL_START_REJECTED");return@post}
            if(pendingConnection.present){resumeConnection();return@post}
            val held=capture
            if(held?.closing==true){
                if(held.workerDone && held.nativeProof.released && held.leaseReturned && !held.quarantined){releasedRecorder=held.nativeProof;capture=null}
                else {mark("LOCAL_PENDING_DISPOSAL");return@post}
            }
            if(voice!=null || capture!=null || scene.management)return@post
            val client=newClient();voice=client;releaseState="local_kws";installCapture(client,ticket)
        }
    }
    private fun stopVoice() {
        stopManagementPrompt()
        val cancelledRequest=connectionSequence.incrementAndGet()
        val stopping=capture; val stoppingVoice=voice
        mark("STOP_ENQUEUE")
        stopping?.requestStop() // before owner queue or model destruction
        owner.post {
        mark("STOP_CONSUME")
        pendingConnection.invalidateThrough(cancelledRequest)
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
