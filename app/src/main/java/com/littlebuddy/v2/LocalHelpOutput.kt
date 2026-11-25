package com.littlebuddy.v2

import android.app.Activity
import android.content.pm.ApplicationInfo
import android.media.AudioAttributes
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import com.littlebuddy.v2.parent.ParentPlaybackSettings

/** Fixed, non-personal material only. No cloud/model API, dynamic text or mic is passed here. */
internal class LocalHelpOutput(private val activity: Activity, private val exit: () -> Unit) {
    private val main = Handler(Looper.getMainLooper())
    private var serial = 0L
    private var active = false
    private var speech: TextToSpeech? = null
    private var available = false
    private var pending: Pair<Long, ParentPlaybackSettings>? = null
    private var label: TextView? = null
    init {
        speech = TextToSpeech(activity) { status -> main.post {
            val engine = speech ?: return@post
            val trusted = runCatching {
                val flags = activity.packageManager.getApplicationInfo(engine.defaultEngine, 0).flags
                flags and (ApplicationInfo.FLAG_SYSTEM or ApplicationInfo.FLAG_UPDATED_SYSTEM_APP) != 0
            }.getOrDefault(false)
            val voice = if (status == TextToSpeech.SUCCESS && trusted) engine.voices?.firstOrNull {
                it.locale.language == "zh" && !it.isNetworkConnectionRequired &&
                    it.features?.contains(TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED) != true
            } else null
            available = voice != null && engine.setVoice(voice) == TextToSpeech.SUCCESS
            if (available) engine.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            pending?.let { (ticket, settings) -> if (active && ticket == serial) speak(ticket, settings) }
        } }
    }
    fun show(settings: ParentPlaybackSettings, audible: Boolean = true, released: Boolean = audible) {
        stop(); active = true; val ticket = serial; pending = if (audible) ticket to settings else null
        val body = LinearLayout(activity).apply { orientation = LinearLayout.VERTICAL; setPadding(32, 40, 32, 32) }
        body.addView(TextView(activity).apply { text = TEXT; textSize = 24f; isSaveEnabled = false })
        label = TextView(activity).apply {
            text = if (released) "本机安全帮助；原对话收音与上传已结束。" else "正在停下旧对话；本机帮助文字独立于云端。"
            isSaveEnabled = false
        }
        body.addView(label)
        body.addView(Button(activity).apply { text = "回到眼睛"; setOnClickListener {
            if (active && ticket == serial) { stop(); exit() }
        } })
        activity.setContentView(body)
        if (available && audible) speak(ticket, settings)
        else label?.text = if (!released) "旧音频资源尚未确认释放；本机帮助文字仍可阅读。" else
            "本机安全帮助已显示；没有已安装且可用的系统离线中文语音时不调用云端。"
    }
    private fun speak(ticket: Long, settings: ParentPlaybackSettings) {
        if (!active || ticket != serial || !available) return
        val engine = speech ?: return
        engine.setSpeechRate(settings.rate / 100f); engine.setPitch(1f)
        val parameters = Bundle().apply { putFloat(TextToSpeech.Engine.KEY_PARAM_VOLUME, settings.volume / 100f) }
        if (engine.speak(TEXT, TextToSpeech.QUEUE_FLUSH, parameters, "local-help-$ticket") != TextToSpeech.SUCCESS)
            label?.text = "本机语音暂不可用，帮助文字仍可阅读。"
        pending = null
    }
    fun stop() { active = false; serial++; pending = null; label = null; speech?.stop() }
    fun close() { stop(); speech?.shutdown(); speech = null }
    companion object {
        const val TEXT = "我们先停一下。我现在不能安全地继续这个回答。你可以找信任、愿意帮助你的成年人；如果你正感到害怕或可能受伤，先到安全的地方。"
    }
}
