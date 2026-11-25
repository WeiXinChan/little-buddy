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
    private var imageRoute: AndroidImageRoute? = null
    private var eyesAttached = false
    private var capture: Capture? = null
    private var exitCapture: ManagementCapture? = null
    @Volatile private var transportRevision=0L
    @Volatile private var managementRevision=0L
    private var releasedRecorder = RecorderProof()
    private var releasedExitRecorder = RecorderProof()
    private var releasedPlayer = PlayerProof()
    private var execution = ParentPlaybackSettings()
    private var budget: PlaybackBudget? = null
    private var panel: AndroidParentPanel? = null
    private var help: LocalHelpOutput? = null
    private val pageRequests=ManagementPageRequests()
    private var managementRequested: Boolean
        get()=pageRequests.requested(managementRevision)
        set(value) { if (value) pageRequests.immediate(managementRevision) else pageRequests.clear() }
    @Volatile private var managementVisible = false
    private var helpVisible = false
    private var managementReturning=false
    @Volatile private var foreground = false
    private var permissionRequested = false
    @Volatile private var connectionNotice="尚未配置V2连接；进入家长验证后可导入已发行的配置。"
    private fun eyes() {
        if (eyesAttached) return
        imageRoute?.clear()
        val frame = android.widget.FrameLayout(this)
        val eyes = V2EyesView(this) { requestParentManagement() }.also { it.onLocalHelp = { showLocalHelp() } }
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
                    runOnUiThread { if (ticket==managementRevision) { managementRequested=false; managementReturning=false; showLocalHelp() } }; return@post }
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
        panel=AndroidParentPanel(this, { leaveManagement() }, { stopVoice() }, { connectionNotice }).also { it.open() }
        startExitCapture(ticket)
    }
    private fun startExitCapture(ticket: Long) { owner.post {
        if (ticket!=managementRevision || !foreground || !managementVisible || exitCapture!=null ||
            releaseState=="quarantined" || voice?.quarantined==true || checkSelfPermission(Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED) return@post
        exitCapture=ManagementCapture(assets,owner,
            { foreground && managementVisible && ticket==managementRevision },
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
        if (entry==null) { helpVisible=false; help?.stop(); managementRequested=true; managementReturning=false; imageRoute?.clear() }
        owner.post {
            if (ticket!=managementRevision || !foreground) return@post
            val client=voice
            if (entry!=null && (client==null || !client.acceptManagementEntry(entry) {
                reservation!=null && pageRequests.claim(reservation)
            })) return@post
            val playerQuiet=client?.stopForManagement() ?: true
            capture?.close(); capture?.let { releasedRecorder=it.nativeProof }
            val recorderQuiet=capture?.quarantined!=true
            if (recorderQuiet) capture=null
            if (!playerQuiet || !recorderQuiet) {
                client?.close(); releaseState="quarantined"
                runOnUiThread { if (ticket==managementRevision) { managementRequested=false; showLocalHelp() } }; return@post
            }
            releaseState="management"
            if (client==null || !client.pauseManagement()) runOnUiThread { openManagementPage(ticket) }
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
                val connection = configuration?.connection
                if (connection==null) {
                    connectionNotice=if (configuration==null) "安全配置不可用或尚未初始化；请从家长验证检查，不会自动连接。"
                        else "尚未配置V2连接；PIN验证后选择系统验证并导入连接配置。"
                    return@runOnUiThread
                }
                if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                    if (!permissionRequested) { permissionRequested = true; requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 804) }
                    return@runOnUiThread
                }
                if (runCatching { connection.requireRunnable() }.isFailure) {
                    connectionNotice="旧直连回环配置不可运行，请家长重新导入V2私有SSH配置。"; return@runOnUiThread
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
            if (ticket != transportRevision || !foreground || voice != null || capture != null || releaseState == "quarantined") return@post
            releaseState = "active"; budget = PlaybackBudget(android.os.SystemClock::elapsedRealtime, settings.durationSeconds)
            val ssh=try { sshUser?.let { com.littlebuddy.v2.transport.V2Ssh(
                com.littlebuddy.v2.transport.V2SshProfile.load(this@V2VoiceActivity,it)) } }
                catch (_: Exception) { connectionNotice="V2私有传输配置不可用"; releaseState="released"; return@post }
            val http=try { val base=okhttp3.OkHttpClient.Builder().proxy(java.net.Proxy.NO_PROXY)
                .followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false).build()
                ssh?.client(base) ?: base }
                catch (_: Exception) { ssh?.close(); releaseState="released"; return@post }
            val client = VoiceClient(owner, { status ->
                connectionNotice=when(status) {
                    "incompatible" -> "服务协议不兼容，儿童收音未启用；请管理员核对候选包与服务契约。"
                    "compatibility" -> "正在核对已配置服务协议；核对前不启动儿童收音。"
                    "wake", "listening", "speaking" -> "V2连接与协议已核对；退出管理回待唤醒。"
                    else -> "连接暂不可用，不代表配置发行或设备验收成功。"
                }
                if (status == "listening" && voice?.isAwake == true) budget?.begin()
            }, { images?.clear() }, { _, _ -> error("unsupported visual effect") }, { runOnUiThread { if (ticket == transportRevision) showLocalHelp() } },
                playbackSettings = settings,
                localHelp = { runOnUiThread { if (ticket == transportRevision) showLocalHelp() } },
                management = { entry -> runOnUiThread { if (ticket == transportRevision) requestParentManagement(entry) } },
                permitted = { foreground && ticket == transportRevision }, images = images,
                managed = { phase -> runOnUiThread { if (ticket==transportRevision) managementChanged(phase) } },
                sessionEnded = { runOnUiThread { if (ticket==transportRevision) {
                    managementRevision++; releaseAudio { quiet -> if (quiet && foreground) { eyes(); resumeConfigured() } }
                } } }, requiredContract=ReleaseCompatibility.CONTRACT,
                http=http, closeTransport={ ssh?.close() }, ready={ if (ticket==transportRevision && foreground && !managementRequested && !managementVisible) startChildCapture(checkNotNull(voice),ticket) })
            voice = client
            try { client.connect(address, credential)
                // Capture starts only from the authenticated, compatible scope callback.
            } catch (_: Exception) { runOnUiThread { if (ticket == transportRevision) showLocalHelp() } }
        }
    }
    private fun startChildCapture(client: VoiceClient, ticket: Long) {
        if (capture!=null || exitCapture!=null || releaseState=="quarantined") return
        capture=Capture(assets,owner,client,
            allowed={ foreground && ticket==transportRevision && !managementRequested && !managementVisible }) {
            runOnUiThread { if (ticket==transportRevision) showLocalHelp() }
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
        transportRevision++; imageRoute?.clear()
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
    private fun showLocalHelp() {
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
    override fun onResume() {
        super.onResume(); foreground = true
        if (managementVisible && hasWindowFocus()) { panel?.open(); startExitCapture(managementRevision) }
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
            if (managementVisible) { panel?.open(); startExitCapture(managementRevision) }
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
