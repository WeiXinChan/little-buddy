package com.littlebuddy

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.littlebuddy.voice.Deadline
import com.littlebuddy.voice.SimulatedReply
import com.littlebuddy.voice.VoiceRound
import com.littlebuddy.voice.VoiceRound.Phase

open class SimActivity : Activity() {
    private val dispatcher = Handler(Looper.getMainLooper())
    private lateinit var round: VoiceRound
    private var audio: AndroidAudio? = null
    private lateinit var status: TextView
    private lateinit var start: Button
    private lateinit var finish: Button
    private lateinit var stop: Button
    private var permissionPending = false
    private var resumed = false
    private var startAfterPermission = false
    private var audioError = false

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
            text = "瓦力 · 本地模拟"
            textSize = 28f
            gravity = Gravity.CENTER
        })
        content.addView(TextView(this).apply {
            text = "唤醒、ASR、LLM、TTS 均为模拟。麦克风仅在本机检测音量，扬声器播放提示音。"
            textSize = 16f
            gravity = Gravity.CENTER
        })
        status = TextView(this).apply {
            textSize = 22f
            gravity = Gravity.CENTER
            setPadding(0, dp(12), 0, dp(12))
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        content.addView(status)

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
            frame = { operation, speech, endpoint ->
                round.captureFrame(operation, speech)
                if (endpoint) round.endCapture(operation)
            },
            failed = {
                audioError = true
                round.audioFailed(it)
            },
            played = { round.played(it) },
            released = { round.released(it) },
        )
        val reply = SimulatedReply(deadline, { id, segment -> round.segment(id, segment) },
            { id, last -> round.endReply(id, last) })
        return VoiceRound(checkNotNull(audio), reply, deadline, changed)
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
        audio?.close()
        super.onDestroy()
    }

    private fun requestStart() {
        audioError = false
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
            round.start(game = true)
        }
    }

    private fun render(phase: Phase, completed: Int) {
        val label = when (phase) {
            Phase.INACTIVE -> "已暂停"
            Phase.IDLE -> when {
                audioError -> "录音或播放失败，请检查麦克风权限及音频设备"
                completed == 3 -> "三轮完成"
                else -> "点按开始，模拟唤醒"
            }
            Phase.OPENING -> "正在打开麦克风"
            Phase.LISTENING -> "正在听"
            Phase.WAITING -> "正在等待模拟回复"
            Phase.PLAYING -> "正在播放提示音"
            Phase.CLEANING -> "正在切换音频"
            Phase.UNAVAILABLE -> "音频清理超时，请重新打开应用"
        }
        status.text = "$label · $completed / 3"
        start.isEnabled = !permissionPending && phase != Phase.INACTIVE && phase != Phase.UNAVAILABLE
        finish.isEnabled = phase == Phase.LISTENING
        stop.isEnabled = phase != Phase.INACTIVE && phase != Phase.IDLE
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density + 0.5f).toInt()

    private companion object {
        const val MICROPHONE_REQUEST = 1
    }
}
