package com.littlebuddy

import android.Manifest
import android.app.Activity
import android.app.KeyguardManager
import android.content.Intent
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
    private var imageRoute: AndroidImageRoute? = null
    private var eyesAttached = false
    @Volatile private var eyeRevision=0L
    private val captureRevision=java.util.concurrent.atomic.AtomicLong()
    private val diagnosticActivity=PinDiagnostic.nextActivity()
    private fun diagnosticScope(transport:Long=transportRevision,capture:Long=captureRevision.get())=
        PinDiagnostic.Scope(diagnosticActivity,transport,capture)
    private fun lifecycleDiagnostic(stage:PinDiagnostic.RuntimeStage,restored:Boolean=false,launcher:Boolean=false) {
        PinDiagnostic.runtime(PinDiagnostic.RuntimeEvent(stage,diagnosticScope(),restored=restored,launcher=launcher))
    }
    private var eyeView:V2EyesView?=null
    private val eyeState=EyeState()
    private fun resetEyes() {
        val token=EyeToken(transportRevision,++eyeRevision)
        eyeState.activate(token);eyeView?.show(eyeState.mood)
    }
    private fun publishEyes(ticket:Long,change:(EyeState,EyeToken)->Unit) {
        val page=eyeRevision
        runOnUiThread {
            if(ticket!=transportRevision || page!=eyeRevision || !foreground || !hasWindowFocus() ||
                !eyesAttached || managementRequested || managementVisible || helpVisible)return@runOnUiThread
            change(eyeState,EyeToken(ticket,page));eyeView?.show(eyeState.mood)
        }
    }
    private fun silenceEyes() {
        eyeState.revoke();eyeRevision++;eyeView?.show(EyeMood.IDLE)
    }
    private fun cancelRecorders() {
        captureRevision.incrementAndGet()
        capture?.requestCancel();exitCapture?.requestCancel()
    }
    @Volatile private var capture: Capture? = null
    @Volatile private var exitCapture: ManagementCapture? = null
    @Volatile private var transportRevision=0L
    @Volatile private var managementRevision=0L
    private var releasedRecorder = RecorderProof()
    private var releasedExitRecorder = RecorderProof()
    private var releasedPlayer = PlayerProof()
    private var execution = ParentPlaybackSettings()
    private var budget: PlaybackBudget? = null
    private var panel: AndroidParentPanel? = null
    private val publicKeyFile by lazy { AndroidPublicKeyFile(this) }
    private var help: LocalHelpOutput? = null
    private val pageRequests=ManagementPageRequests()
    private var managementRequested: Boolean
        get()=pageRequests.requested(managementRevision)
        set(value) { if (value) pageRequests.immediate(managementRevision) else pageRequests.clear() }
    @Volatile private var managementVisible = false
    private var helpVisible = false
    private val retryGate = RuntimeRetryGate()
    private var managementReturning=false
    @Volatile private var foreground = false
    @Volatile private var focused = false
    private var permissionRequested = false
    @Volatile private var connectionNotice="正在检查连接。"
    private fun eyes() {
        if (eyesAttached) return
        imageRoute?.clear()
        val frame = android.widget.FrameLayout(this)
        val eyes = V2EyesView(this) { requestParentManagement() }
        eyeView=eyes;resetEyes()
        frame.addView(eyes)
        val picture = android.widget.ImageView(this).apply {
            scaleType = android.widget.ImageView.ScaleType.FIT_CENTER
            setBackgroundColor(android.graphics.Color.BLACK); visibility = android.view.View.GONE
            importantForAccessibility = android.view.View.IMPORTANT_FOR_ACCESSIBILITY_NO
            // Same hidden management gesture remains available over a revealed picture.
            setOnTouchListener { _, event -> eyes.onTouchEvent(event) }
        }
        frame.addView(picture, android.widget.FrameLayout.LayoutParams(-1, -1))
        imageRoute = AndroidImageRoute(this, configurationWorker, picture)
        setContentView(frame)
        eyesAttached = true
    }
    internal fun observeNative(result: (NativeEvidence) -> Unit) { owner.post {
        result(NativeEvidence(capture?.nativeProof ?: releasedRecorder, voice?.nativeProof() ?: releasedPlayer))
    } }
    internal fun withVoice(action: (VoiceClient) -> Unit) { owner.post { voice?.let(action) } }
    internal fun observeManagementRecorder(result: (RecorderProof) -> Unit) { owner.post {
        result(exitCapture?.nativeProof ?: releasedExitRecorder)
    } }
    private fun leaveManagement() {
        publicKeyFile.cancel()
        retryGate.explicitParentRetry()
        PinDiagnostic.event(PinDiagnostic.Stage.TECHNICAL, PinDiagnostic.Reason.PARENT_RETRY)
        val ticket=++managementRevision
        managementVisible=false; managementRequested=true; managementReturning=true
        panel?.close(); panel=null; eyes()
        val resumedImages=imageRoute
        // Exit needs no PIN. It is a current page action, not a restoration of its revoked Grant.
        configurationWorker.execute {
            val configuration=runCatching { AndroidParentRuntime.load(this).childConfiguration() }.getOrNull()
            owner.post {
                val released=closeExitCapture()
                if (ticket!=managementRevision || !foreground) return@post
                val client=voice
                if (!released) { client?.close(); releaseState="quarantined"
                    runOnUiThread { if (ticket==managementRevision) { managementRequested=false; managementReturning=false; showTechnicalFailure(PinDiagnostic.Reason.RELEASE_FAILED) } }; return@post }
                if (configuration!=null && client!=null) {
                    budget?.tighten(configuration.playback.durationSeconds)
                    if (client.resumeManagement(configuration.playback,resumedImages)) return@post
                }
                // Lost/expired connection never borrows the receipt for a replacement session.
                runOnUiThread { if (ticket==managementRevision) {
                    managementRequested=false; managementReturning=false; releaseAudio { quiet -> if (quiet && ticket==managementRevision) resumeConfigured() }
                } }
            }
        }
    }
    private fun openManagementPage(ticket: Long) {
        if (ticket!=managementRevision || !foreground || !hasWindowFocus() || !managementRequested) return
        managementRequested=false; managementVisible=true; eyesAttached=false
        eyeState.revoke();eyeView?.show(EyeMood.IDLE);eyeRevision++
        panel=AndroidParentPanel(this, { leaveManagement() }, { stopVoice() }, { connectionNotice },
            savePublicKey = { model -> publicKeyFile.begin { publish, failed ->
                model.exportTransportKey({ com.littlebuddy.v2.transport.V2SshIdentity.load(create=true).registrationKey() }, publish, failed)
            } },
            pageChanged = { state -> if (state.mode != PanelMode.SETTINGS || state.busy) publicKeyFile.pageUnavailable() },
            configurationSaved = {
                connectionNotice="连接已保存，退出管理后连接。"
                PinDiagnostic.event(PinDiagnostic.Stage.CONFIG, PinDiagnostic.Reason.SAVED_LOCAL)
            }
        ).also { it.open() }
        startExitCapture(ticket)
    }
    private fun startExitCapture(ticket: Long) { owner.post {
        if (ticket!=managementRevision || !foreground || !focused || !managementVisible || exitCapture!=null ||
            releaseState=="quarantined" || voice?.quarantined==true || checkSelfPermission(Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED) return@post
        exitCapture=ManagementCapture(assets,owner,
            { foreground && focused && managementVisible && ticket==managementRevision },
            { runOnUiThread { if (ticket==managementRevision && managementVisible && foreground && hasWindowFocus()) panel?.exit() } },
            { runOnUiThread { if (ticket==managementRevision) stopVoice() } }).also { it.start() }
    } }
    private fun closeExitCapture(): Boolean {
        val old=exitCapture ?: return true
        old.close(); releasedExitRecorder=old.nativeProof
        if (old.quarantined) return false
        exitCapture=null; return true
    }
    private fun managementChanged(phase: ManagementState.Phase) {
        when (phase) {
            ManagementState.Phase.PAUSED -> openManagementPage(managementRevision)
            ManagementState.Phase.WAITING_WAKE -> {
                if (!managementRequested || managementVisible || !foreground || !hasWindowFocus()) return
                managementRequested=false; managementReturning=false; eyes()
                val ticket=transportRevision
                owner.post { if (foreground && ticket==transportRevision && !managementRequested && !managementVisible) {
                    voice?.let { startChildCapture(it,ticket) }
                } }
            }
            ManagementState.Phase.DEAD -> {
                if (managementReturning) {
                    managementRequested=false; managementReturning=false
                    val ticket=managementRevision
                    releaseAudio { quiet -> if (quiet && ticket==managementRevision) { eyes(); resumeConfigured() } }
                    return
                }
                if (managementRequested && !managementVisible) {
                    // Local settings remain available after a failed control handshake; no receipt is synthesized.
                    openManagementPage(managementRevision)
                }
            }
            else -> Unit
        }
    }
    /** Stop child hardware first, retain only the authenticated transport while requesting pause. */
    internal fun requestParentManagement(entry: ManagementEntry?=null) {
        if (!foreground || !hasWindowFocus() || managementRequested || managementVisible) return
        if (getSystemService(KeyguardManager::class.java).isKeyguardLocked) return
        managementReturning=false
        val ticket=++managementRevision
        val reservation=if (entry!=null) pageRequests.reserve(ticket) else null
        if (entry==null) { helpVisible=false; help?.stop(); managementRequested=true; managementReturning=false;silenceEyes();imageRoute?.clear() }
        owner.post {
            if (ticket!=managementRevision || !foreground) return@post
            val client=voice
            if (entry!=null && (client==null || !client.acceptManagementEntry(entry) {
                reservation!=null && pageRequests.claim(reservation)
            })) return@post
            if(entry!=null)runOnUiThread {if(ticket==managementRevision && managementRequested)silenceEyes()}
            val playerQuiet=client?.stopForManagement() ?: true
            captureRevision.incrementAndGet();capture?.requestCancel()
            capture?.close(); capture?.let { releasedRecorder=it.nativeProof }
            val recorderQuiet=capture?.quarantined!=true
            if (recorderQuiet) capture=null
            if (!playerQuiet || !recorderQuiet) {
                client?.close(); releaseState="quarantined"
                retryGate.technicalFailure()
                PinDiagnostic.event(PinDiagnostic.Stage.TECHNICAL,PinDiagnostic.Reason.RELEASE_FAILED)
                runOnUiThread { if (ticket==managementRevision) {
                    connectionNotice="收音暂不可用，已安全暂停。"
                    openManagementPage(ticket)
                } }; return@post
            }
            releaseState="management"
            if (client==null || !client.pauseManagement()) runOnUiThread { openManagementPage(ticket) }
        }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        AndroidPinDiagnostic.enable()
        lifecycleDiagnostic(PinDiagnostic.RuntimeStage.ACTIVITY_CREATE,savedInstanceState!=null,intent?.action==Intent.ACTION_MAIN)
        help = LocalHelpOutput(this) {
            PinDiagnostic.event(PinDiagnostic.Stage.HELP, PinDiagnostic.Reason.RETURN)
            helpVisible = false; eyes(); resumeConfigured()
        }
        eyes()
        if (Build.VERSION.SDK_INT >= 33) onBackInvokedDispatcher.registerOnBackInvokedCallback(
            android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT) { back() }
    }
    private fun resumeConfigured() {
        if (!retryGate.automaticAllowed || !foreground || !hasWindowFocus() || managementVisible || managementRequested || helpVisible) return
        val ticket = managementRevision
        configurationWorker.execute {
            val configResult = AndroidParentRuntime.configuration(this)
            val configuration = configResult.configuration
            runOnUiThread {
                if (!retryGate.automaticAllowed || ticket != managementRevision || !foreground || !hasWindowFocus() || managementVisible || managementRequested || helpVisible) return@runOnUiThread
                if (configuration != null) execution = configuration.playback
                val connection = configuration?.connection
                PinDiagnostic.event(PinDiagnostic.Stage.CONFIG, when(configResult.status) {
                    ConfigurationStatus.LOAD_FAILED -> PinDiagnostic.Reason.CONFIG_LOAD_FAILED
                    ConfigurationStatus.MIGRATION_FAILED -> PinDiagnostic.Reason.CONFIG_MIGRATION_FAILED
                    ConfigurationStatus.CHILD_MISSING -> PinDiagnostic.Reason.CONFIG_CHILD_MISSING
                    ConfigurationStatus.NO_CONNECTION -> PinDiagnostic.Reason.CONFIG_CONNECTION_MISSING
                    ConfigurationStatus.READY -> PinDiagnostic.Reason.READY
                })
                if (connection==null) {
                    connectionNotice=if (configuration==null) "连接配置暂不可用，请长按右下角查看管理状态。"
                        else "本机连接尚未准备好，请长按右下角查看管理状态。"
                    return@runOnUiThread
                }
                if (BuildConfig.CONFIGURATION_DIAGNOSTIC_ONLY) {
                    connectionNotice="本次连接配置检查已完成，诊断版本暂不启动语音。"
                    return@runOnUiThread
                }
                connectionNotice="正在连接。"
                if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                    if (!permissionRequested) { permissionRequested = true; requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 804) }
                    return@runOnUiThread
                }
                if (runCatching { connection.requireRunnable() }.isFailure) {
                    connectionNotice="现有连接格式不可运行，请在管理中查看状态。"; return@runOnUiThread
                }
                execution = configuration.playback
                startVoice(connection.address, connection.credential, connection.sshUser)
            }
        }
    }
    /** Internal native regression seam; production calls this only after encrypted provisioning. */
    internal fun startVoice(address: String, credential: String, sshUser: String? = null) {
        check(!managementRequested && !managementVisible && !helpVisible)
        check(hasWindowFocus() && checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
        check(!getSystemService(KeyguardManager::class.java).isKeyguardLocked)
        val ticket = transportRevision; val settings = execution; val images = imageRoute
        owner.post {
            if (!retryGate.automaticAllowed || ticket != transportRevision || !foreground || !focused || voice != null || capture != null || releaseState == "quarantined") return@post
            PinDiagnostic.beginRuntime()
            releaseState = "active"; budget = PlaybackBudget(android.os.SystemClock::elapsedRealtime, settings.durationSeconds)
            val ssh=try { sshUser?.let { com.littlebuddy.v2.transport.V2Ssh(
                com.littlebuddy.v2.transport.V2SshProfile.load(this@V2VoiceActivity,it)) } }
                catch (error: Exception) { PinDiagnostic.runtimeError(PinDiagnostic.Stage.SSH,error); runOnUiThread { if(ticket==transportRevision) showTechnicalFailure(PinDiagnostic.Reason.SSH_ERROR) }; return@post }
            val http=try { val base=okhttp3.OkHttpClient.Builder().proxy(java.net.Proxy.NO_PROXY)
                .followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false).build()
                ssh?.client(base) ?: base }
                catch (error: Exception) { PinDiagnostic.runtimeError(PinDiagnostic.Stage.WSS,error); ssh?.close(); runOnUiThread { if(ticket==transportRevision) showTechnicalFailure(PinDiagnostic.Reason.OTHER_ERROR) }; return@post }
            var lastLog: com.littlebuddy.v2.feedback.LogStage?=null
            var lastFailure=PinDiagnostic.Reason.OTHER_ERROR
            val client = VoiceClient(owner, statusCallback@ { status ->
                if(ticket!=transportRevision || !foreground || !focused)return@statusCallback
                lastFailure=when(status) {
                    "network" -> PinDiagnostic.Reason.NETWORK
                    "closed" -> PinDiagnostic.Reason.CLOSED
                    "incompatible" -> PinDiagnostic.Reason.INCOMPATIBLE
                    "protocol" -> PinDiagnostic.Reason.PROTOCOL_FAILED
                    "release" -> PinDiagnostic.Reason.RELEASE_FAILED
                    else -> PinDiagnostic.Reason.OTHER_ERROR
                }
                publishEyes(ticket){state,key->state.status(key,status)}
                val stage=when(status) { "compatibility","wake"->com.littlebuddy.v2.feedback.LogStage.CONNECT
                    "listening"->com.littlebuddy.v2.feedback.LogStage.RECOGNIZE;else->null }
                if(stage!=null && stage!=lastLog) { lastLog=stage;com.littlebuddy.v2.feedback.AndroidFeedbackRuntime.record(this@V2VoiceActivity,stage) }
                connectionNotice=when(status) {
                    "incompatible" -> "服务暂不可用，收音已暂停。"
                    "compatibility" -> "正在连接。"
                    "wake", "listening", "speaking", "thinking", "waiting_complete", "waiting_incomplete", "waiting_thinking", "clarify" -> "已连接，退出管理后等待唤醒。"
                    else -> "连接暂不可用。"
                }
                if (status == "listening" && voice?.isAwake == true) budget?.begin()
            }, { images?.inputChanged() }, { _, _ -> error("unsupported visual effect") }, { runOnUiThread { if (ticket == transportRevision) showTechnicalFailure(lastFailure) } },
                playbackSettings = settings,
                localHelp = { runOnUiThread { if (ticket == transportRevision) showLocalHelp() } },
                management = { entry -> runOnUiThread { if (ticket == transportRevision) requestParentManagement(entry) } },
                permitted = { foreground && focused && ticket == transportRevision }, images = images,
                managed = { phase -> runOnUiThread { if (ticket==transportRevision) managementChanged(phase) } },
                sessionEnded = { runOnUiThread { if (ticket==transportRevision && foreground && focused && !managementRequested && !managementVisible && !helpVisible) {
                    val page=++managementRevision
                    releaseAudio { quiet -> if (quiet && ticket+1==transportRevision && page==managementRevision && foreground && focused &&
                        !managementRequested && !managementVisible && !helpVisible) { eyes(); resumeConfigured() } }
                } } }, requiredContract=ReleaseCompatibility.CONTRACT,
                http=http, closeTransport={ ssh?.close() }, diagnosticScope=diagnosticScope(ticket,0), actualOutput={playing->
                    if(playing && foreground && focused && ticket==transportRevision && lastLog!=com.littlebuddy.v2.feedback.LogStage.PLAY) {
                        lastLog=com.littlebuddy.v2.feedback.LogStage.PLAY
                        com.littlebuddy.v2.feedback.AndroidFeedbackRuntime.record(this@V2VoiceActivity,com.littlebuddy.v2.feedback.LogStage.PLAY)
                    }
                    publishEyes(ticket){state,key->state.output(key,playing)}
                }, ready={ if (ticket==transportRevision && foreground && !managementRequested && !managementVisible) startChildCapture(checkNotNull(voice),ticket) })
            voice = client
            try { client.connect(address, credential)
                // Capture starts only from the authenticated, compatible scope callback.
            } catch (error: Exception) { PinDiagnostic.runtimeError(PinDiagnostic.Stage.WSS,error); runOnUiThread { if (ticket == transportRevision) showTechnicalFailure(PinDiagnostic.Reason.OTHER_ERROR) } }
        }
    }
    private fun startChildCapture(client: VoiceClient, ticket: Long) {
        if (!foreground || !focused || ticket!=transportRevision || managementRequested || managementVisible || capture!=null || exitCapture!=null || releaseState=="quarantined") return
        val recorderTicket=captureRevision.incrementAndGet()
        publishEyes(ticket){state,key->state.beginRecorder(key,recorderTicket)}
        capture=Capture(assets,owner,client,
            allowed={ foreground && focused && ticket==transportRevision && recorderTicket==captureRevision.get() && !managementRequested && !managementVisible },
            recording={active->publishEyes(ticket){state,key->state.recording(key,recorderTicket,active)}},
            diagnosticScope=diagnosticScope(ticket,recorderTicket),modelDirectory=codeCacheDir) {
            runOnUiThread {
                val currentTransport=transportRevision;val currentCapture=captureRevision.get()
                val apply=CaptureFailureGate.current(ticket,recorderTicket,currentTransport,currentCapture,
                    foreground && focused && !managementRequested && !managementVisible && !helpVisible && voice===client)
                PinDiagnostic.runtime(PinDiagnostic.RuntimeEvent(if(apply)PinDiagnostic.RuntimeStage.FAILURE_UI_APPLY else PinDiagnostic.RuntimeStage.FAILURE_UI_RETIRED,
                    diagnosticScope(ticket,recorderTicket),currentTransport=currentTransport,currentCapture=currentCapture))
                if(apply)showTechnicalFailure(PinDiagnostic.Reason.CAPTURE_FAILED)
            }
        }.also { it.start() }
        owner.removeCallbacks(durationLimit); owner.postDelayed(durationLimit,250)
        releaseState="active"
    }
    private val durationLimit = object : Runnable {
        override fun run() {
            if (voice == null) return
            if (budget?.expired() == true) {
                runOnUiThread {
                    val ticket = ++managementRevision
                    if (managementVisible || managementRequested) {
                        releaseAudio { if (ticket==managementRevision && managementRequested && !managementVisible) openManagementPage(ticket) }
                        return@runOnUiThread
                    }
                    releaseAudio { quiet -> if (quiet && ticket == managementRevision && foreground && hasWindowFocus()) {
                        Toast.makeText(this@V2VoiceActivity, "这一轮先休息一下，再玩时重新唤醒。", Toast.LENGTH_LONG).show()
                        eyes(); resumeConfigured()
                    } }
                }
            } else owner.postDelayed(this, 250)
        }
    }
    private fun releaseAudio(done: (Boolean) -> Unit = {}) {
        PinDiagnostic.runtime(PinDiagnostic.RuntimeEvent(PinDiagnostic.RuntimeStage.TRANSPORT_RETIRE,diagnosticScope()))
        transportRevision++;cancelRecorders();resetEyes();imageRoute?.clear()
        owner.post {
        owner.removeCallbacks(durationLimit)
        voice?.close(); voice?.let { releasedPlayer = it.nativeProof() }
        if (voice?.quarantined != true) voice = null
        capture?.close(); capture?.let { releasedRecorder = it.nativeProof }
        if (capture?.quarantined != true) capture = null
        budget = null
        val exitQuiet=closeExitCapture()
        val quiet = voice == null && capture == null && exitQuiet
        releaseState = if (quiet) "released" else "quarantined"
        runOnUiThread { done(quiet) }
    } }
    private fun stopVoice() = releaseAudio()
    private fun showTechnicalFailure(reason: PinDiagnostic.Reason) {
        if (!retryGate.technicalFailure()) return
        PinDiagnostic.event(PinDiagnostic.Stage.TECHNICAL, reason)
        PinDiagnostic.event(PinDiagnostic.Stage.TECHNICAL, PinDiagnostic.Reason.HOLD)
        connectionNotice="连接或收音暂不可用，已暂停。退出管理可重试一次。"
        helpVisible=false; help?.stop()
        val ticket=++managementRevision
        releaseAudio { _ ->
            if (ticket==managementRevision && foreground && hasWindowFocus() && !managementVisible && !managementRequested) {
                eyes(); eyeState.status(EyeToken(transportRevision,eyeRevision),"technical_failure");eyeView?.show(eyeState.mood)
                Toast.makeText(this, "技术准备未完成，已暂停自动重试。可从隐藏入口进入家长管理。", Toast.LENGTH_LONG).show()
            }
        }
    }
    private fun showLocalHelp() {
        PinDiagnostic.event(PinDiagnostic.Stage.HELP, PinDiagnostic.Reason.BEGIN)
        if (!foreground || !hasWindowFocus() || managementVisible || managementRequested || helpVisible) return
        helpVisible = true; val ticket = ++managementRevision
        eyesAttached = false
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
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        lifecycleDiagnostic(PinDiagnostic.RuntimeStage.ACTIVITY_NEW_INTENT,launcher=intent.action==Intent.ACTION_MAIN)
    }
    override fun onResume() {
        super.onResume()
        lifecycleDiagnostic(PinDiagnostic.RuntimeStage.ACTIVITY_RESUME); foreground = true
        if (managementVisible && hasWindowFocus()) { panel?.open(); startExitCapture(managementRevision) }
        else if (!managementVisible && !helpVisible) { eyes(); resumeConfigured() }
    }
    override fun onPause() {
        lifecycleDiagnostic(PinDiagnostic.RuntimeStage.ACTIVITY_PAUSE)
        foreground = false;cancelRecorders(); managementRevision++; managementRequested = false
        com.littlebuddy.v2.feedback.AndroidFeedbackRuntime.record(this,com.littlebuddy.v2.feedback.LogStage.CANCEL)
        publicKeyFile.focusLost(); panel?.pause(); helpVisible = false; help?.stop(); stopVoice(); super.onPause()
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
        lifecycleDiagnostic(if(hasFocus)PinDiagnostic.RuntimeStage.ACTIVITY_FOCUS_GAIN else PinDiagnostic.RuntimeStage.ACTIVITY_FOCUS_LOSS)
        super.onWindowFocusChanged(hasFocus)
        focused=hasFocus
        if (!hasFocus) {
            cancelRecorders()
            managementRevision++; managementRequested = false
            publicKeyFile.focusLost(); panel?.focusLost(); helpVisible = false; help?.stop(); stopVoice()
        } else if (foreground) {
            publicKeyFile.focusGained()
            if (managementVisible) { panel?.open(); startExitCapture(managementRevision) }
            else if (!helpVisible) { eyes(); resumeConfigured() }
        }
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (grantResults.any { it != PackageManager.PERMISSION_GRANTED }) stopVoice() else resumeConfigured()
    }
    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: android.content.Intent?) {
        if (!publicKeyFile.result(requestCode, resultCode, data)) super.onActivityResult(requestCode, resultCode, data)
    }
    override fun onDestroy() {
        publicKeyFile.close()
        foreground = false;cancelRecorders(); managementRevision++; managementRequested = false
        panel?.close(); panel = null; help?.close(); help = null
        stopVoice(); owner.post { audioThread.quitSafely() }; configurationWorker.shutdown()
        super.onDestroy()
    }
}
