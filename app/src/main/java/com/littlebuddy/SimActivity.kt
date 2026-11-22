package com.littlebuddy

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.littlebuddy.voice.Deadline
import com.littlebuddy.voice.SimulatedReply
import com.littlebuddy.voice.VoiceRound
import com.littlebuddy.voice.VoiceRound.CaptureEnd
import com.littlebuddy.voice.VoiceRound.Phase
import com.littlebuddy.voice.VoiceRound.ReplyTimeout

open class SimActivity : Activity() {
    private val dispatcher = Handler(Looper.getMainLooper())
    private lateinit var round: VoiceRound
    private var audio: AndroidAudio? = null
    private lateinit var status: TextView
    private var diagnostics: TextView? = null
    private var captureStartedAt = 0L
    private var currentDiagnostic = ""
    private var lastCaptureEnd = ""
    private lateinit var start: Button
    private lateinit var finish: Button
    private lateinit var stop: Button
    private var permissionPending = false
    private var resumed = false
    private var startAfterPermission = false
    private var audioError = false
    protected open val cloudMode = false
    private var cloud: CloudVoice? = null
    private var endpoint: EditText? = null
    private var credential: EditText? = null
    private var cloudError = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
        }
        val scroll = ScrollView(this).apply {
            isFillViewport = true
            addView(content)
            setOnApplyWindowInsetsListener { view, insets ->
                @Suppress("DEPRECATION")
                view.setPadding(
                    insets.systemWindowInsetLeft + dp(16),
                    insets.systemWindowInsetTop + dp(12),
                    insets.systemWindowInsetRight + dp(16),
                    insets.systemWindowInsetBottom + dp(12),
                )
                insets
            }
        }
        content.addView(TextView(this).apply {
            text = if (cloudMode) "瓦力 · 一句交流验证" else "瓦力 · 本地模拟"
            textSize = 28f
            gravity = Gravity.CENTER
        })
        content.addView(TextView(this).apply {
            text = if (cloudMode) "开始后，麦克风音频会发送至填写的私有服务。等待「正在听」后再说话。"
            else "唤醒、ASR、LLM、TTS 均为模拟。麦克风仅在本机检测音量，扬声器播放提示音。"
            textSize = 16f
            gravity = Gravity.CENTER
        })
        if (cloudMode) {
            fun field(label: String, kind: Int) = EditText(this).apply {
                hint = label
                inputType = InputType.TYPE_CLASS_TEXT or kind or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
                isSingleLine = true
                isSaveEnabled = false
                importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
                content.addView(this, LinearLayout.LayoutParams(-1, -2))
            }
            endpoint = field("私有 WSS 地址", InputType.TYPE_TEXT_VARIATION_URI)
            credential = field("设备令牌", InputType.TYPE_TEXT_VARIATION_PASSWORD)
        } else {
            content.addView(Button(this).apply {
                text = "私有语音验证"
                setOnClickListener { startActivity(Intent(this@SimActivity, CloudActivity::class.java)) }
            })
        }
        status = TextView(this).apply {
            textSize = 22f
            gravity = Gravity.CENTER
            setPadding(0, dp(12), 0, dp(12))
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        content.addView(status)
        if (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0) {
            diagnostics = TextView(this).apply { gravity = Gravity.CENTER }
            content.addView(diagnostics)
        }

        val controls = LinearLayout(this)
        fun button(label: String, action: () -> Unit) = Button(this).apply {
            text = label
            minHeight = dp(56)
            setOnClickListener { action() }
            controls.addView(this, LinearLayout.LayoutParams(0, -2, 1f))
        }
        start = button("开始说话") { requestStart() }
        finish = button("结束说话") { round.endCapture() }
        stop = button("停止") { round.stop() }
        content.addView(controls, LinearLayout.LayoutParams(-1, -2))
        setContentView(scroll)

        round = createRound(::render)
        render(round.phase, round.completed)
    }

    protected open fun createRound(changed: (Phase, Int) -> Unit): VoiceRound {
        val deadline = Deadline { milliseconds, action -> dispatcher.postDelayed({ action() }, milliseconds) }
        audio = AndroidAudio(
            dispatcher,
            captureStarted = { cloud?.captureStarted(it) },
            speechDetected = { cloud?.speechDetected(it) },
            frame = { operation, speech, endpoint ->
                round.captureFrame(operation, speech)
                if (endpoint) round.endCapture(operation, CaptureEnd.TAIL_SILENCE)
            },
            failed = {
                audioError = true
                round.audioFailed(it)
            },
            played = { round.played(it) },
            released = { round.released(it) },
            pcm = if (cloudMode) { id, samples, count -> cloud?.upload(id, samples, count) } else null,
            diagnostics = if (diagnostics == null) null else { energy, decision ->
                val elapsed = SystemClock.elapsedRealtime() - captureStartedAt
                currentDiagnostic = "RMS $energy · $decision · ${elapsed} ms"
                renderDiagnostics()
            },
        )
        if (cloudMode) {
            val voice = CloudVoice(
                dispatcher, checkNotNull(audio),
                config = { endpoint!!.text.toString().trim() to credential!!.text.toString() },
                failed = { operation, turn ->
                    cloudError = true
                    if (turn != null) round.replyFailed(turn) else round.audioFailed(operation)
                },
                released = { round.released(it) },
                segment = { id, number, source -> round.stream(id, number, source) },
                ended = { id, count -> round.endReply(id, count) },
            )
            cloud = voice
            return VoiceRound(voice, voice, deadline, true, captureSealed = { operation, reason ->
                voice.captureSealed(operation)
                describeCaptureEnd(reason)
            }, changed = changed)
        }
        val reply = SimulatedReply(deadline, { id, segment -> round.segment(id, segment) },
            { id, last -> round.endReply(id, last) })
        return VoiceRound(checkNotNull(audio), reply, deadline, false,
            captureSealed = { _, reason -> describeCaptureEnd(reason) }, changed = changed)
    }

    override fun onResume() {
        super.onResume()
        resumed = true
        round.foreground(true)
        startIfAuthorized()
    }

    override fun onPause() {
        resumed = false
        round.foreground(false)
        super.onPause()
    }

    override fun onDestroy() {
        dispatcher.removeCallbacksAndMessages(null)
        cloud?.close()
        credential?.text?.clear()
        audio?.close()
        super.onDestroy()
    }

    private fun requestStart() {
        audioError = false
        cloudError = false
        startAfterPermission = true
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            startIfAuthorized()
        } else {
            permissionPending = true
            start.isEnabled = false
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), MICROPHONE_REQUEST)
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, results)
        if (requestCode != MICROPHONE_REQUEST) return
        permissionPending = false
        startAfterPermission = results.firstOrNull() == PackageManager.PERMISSION_GRANTED
        render(round.phase, round.completed)
        if (startAfterPermission) startIfAuthorized()
        else status.text = "请允许麦克风权限后再开始"
    }

    private fun startIfAuthorized() {
        if (resumed && !permissionPending && startAfterPermission &&
            checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            startAfterPermission = false
            round.start(game = !cloudMode)
        }
    }

    private fun render(phase: Phase, completed: Int) {
        if (diagnostics != null) {
            when (phase) {
                Phase.OPENING -> {
                    captureStartedAt = SystemClock.elapsedRealtime()
                    currentDiagnostic = "等待音频帧"
                }
                Phase.INACTIVE -> {
                    currentDiagnostic = ""
                    lastCaptureEnd = ""
                }
                else -> Unit
            }
            renderDiagnostics()
        }
        val label = when (phase) {
            Phase.INACTIVE -> "已暂停"
            Phase.IDLE -> when {
                cloudError -> "连接或语音回复失败，请检查私有地址和设备令牌"
                audioError -> "录音或播放失败，请检查麦克风权限及音频设备"
                round.replyTimeout == ReplyTimeout.FIRST_SEGMENT -> "等待回复超时，请再试一次"
                round.replyTimeout == ReplyTimeout.INCOMPLETE_REPLY -> "回复中断超时，请再试一次"
                round.emptyCapture == VoiceRound.EmptyCapture.NO_FRAMES -> "没收到麦克风声音，请再试一次"
                round.emptyCapture == VoiceRound.EmptyCapture.NO_SPEECH -> "没听清，请再说一次"
                completed == 3 -> "三轮完成"
                else -> if (cloudMode) "点按开始说话" else "点按开始，模拟唤醒"
            }
            Phase.OPENING -> if (cloudMode) "正在连接并打开麦克风" else "正在打开麦克风"
            Phase.LISTENING -> "正在听"
            Phase.WAITING -> if (cloudMode) "正在等待回复" else "正在等待模拟回复"
            Phase.PLAYING -> if (cloudMode) "正在播放回复" else "正在播放提示音"
            Phase.CLEANING -> "正在切换音频"
            Phase.UNAVAILABLE -> "音频清理超时，请重新打开应用"
        }
        status.text = if (cloudMode) label else "$label · $completed / 3"
        start.isEnabled = !permissionPending && phase != Phase.INACTIVE && phase != Phase.UNAVAILABLE
        finish.isEnabled = phase == Phase.LISTENING || phase == Phase.OPENING
        stop.isEnabled = phase != Phase.INACTIVE && phase != Phase.IDLE
    }

    private fun describeCaptureEnd(reason: CaptureEnd) {
        if (diagnostics == null) return
        val label = when (reason) {
            CaptureEnd.MANUAL -> "手动结束"
            CaptureEnd.TAIL_SILENCE -> "句末静音"
            CaptureEnd.NO_FRAME_TIMEOUT -> "无帧超时"
            CaptureEnd.MAX_DURATION -> "录音达到时限"
        }
        val elapsed = SystemClock.elapsedRealtime() - captureStartedAt
        lastCaptureEnd = "$label · ${elapsed} ms"
    }

    private fun renderDiagnostics() {
        diagnostics?.text = listOf(currentDiagnostic, lastCaptureEnd)
            .filter { it.isNotEmpty() }.joinToString("\n")
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density + 0.5f).toInt()

    private companion object {
        const val MICROPHONE_REQUEST = 1
    }
}

class CloudActivity : SimActivity() {
    override val cloudMode = true
}
