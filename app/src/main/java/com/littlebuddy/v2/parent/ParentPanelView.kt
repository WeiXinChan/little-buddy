package com.littlebuddy.v2.parent

import android.app.Activity
import android.text.InputFilter
import android.text.InputType
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/** Local settings widgets. No PIN or system-authentication controls. */
internal class ParentPanelView(private val activity: Activity, private val model: ParentPanelModel,
    private val feedback: ParentFeedbackRoute = AndroidParentFeedbackRoute,
    private val connectionNotice: () -> String = { "" },
    private val savePublicKey: () -> Unit = {},
    private val connectionPreset: () -> DeviceConnectionPreset? = { null }) {
    private val inputs = mutableListOf<EditText>()
    private val routes = ParentRouteSlot<ParentRoutePage>({ it.pause() }, { it.close() })
    fun pause() { clearInputs(); routes.pause() }
    fun close() { clearInputs(); routes.close() }
    private fun clearInputs() { inputs.forEach { it.text?.clear() }; inputs.clear() }
    fun render(state: PanelState) {
        if (state.mode == PanelMode.OWNER_PIN) PinDiagnostic.event(PinDiagnostic.Stage.RENDER,
            if (state.busy) PinDiagnostic.Reason.SAVE_IN_PROGRESS else PinDiagnostic.Reason.SUCCESS)
        clearInputs()
        val route = if (state.mode == PanelMode.FEEDBACK) model.currentRoute() else null
        if (route != null) {
            routes.mount(route.revision, {
                feedback.create(activity, route.domain, route.grant) {
                    activity.runOnUiThread { model.routeExit(route.revision) }
                }
            }, { page -> activity.setContentView(page.view) }, {
                model.routeFailed(route.revision) { routes.close(route.revision) }
            })
            return
        }
        routes.close()
        val token = model.viewToken
        val body = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL; setPadding(32, 24, 32, 24); isSaveEnabled = false
        }
        fun label(text: String, size: Float = 18f) = TextView(activity).apply {
            this.text = text; textSize = size; body.addView(this)
        }
        fun button(text: String, enabled: Boolean = !state.busy, action: () -> Unit) = Button(activity).apply {
            this.text = text; isEnabled = enabled; isSaveEnabled = false
            setOnClickListener { model.userAction(token) { action() } }; body.addView(this)
        }
        label("家长管理", 26f)
        if (state.mode == PanelMode.SETTINGS) label(if (model.hasSavedConnection) "本机连接已保存" else "尚未连接",14f)
        if (state.mode == PanelMode.SETTINGS && model.hasSavedConnection) label(connectionNotice(),14f)
        label(if (state.notice == PanelNotice.NONE && state.mode == PanelMode.SETTINGS)
            if (model.directManagement) "退出或闲置后关闭本次管理页面。" else "已验证。退出或闲置后会锁定。" else notice(state.notice))
        when (state.mode) {
            PanelMode.VERIFY, PanelMode.CHANGE_PIN, PanelMode.OWNER_PIN ->
                label("管理页面已失效，请退出后长按右下角重新进入。")
            PanelMode.SETTINGS -> {
                label("本地音量上限（0–100）")
                val volume = EditText(activity).apply {
                    inputType = InputType.TYPE_CLASS_NUMBER; filters = arrayOf(InputFilter.LengthFilter(3))
                    isSaveEnabled = false; setText(state.volume?.toString() ?: "")
                    importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
                    isEnabled = !state.busy; body.addView(this)
                }
                label("语速（85–115%）与每次互动上限（60–600秒）")
                val rate = EditText(activity).apply { inputType = InputType.TYPE_CLASS_NUMBER
                    setText((state.settings?.rate ?: 100).toString()); isSaveEnabled = false; body.addView(this) }
                val duration = EditText(activity).apply { inputType = InputType.TYPE_CLASS_NUMBER
                    setText((state.settings?.durationSeconds ?: 600).toString()); isSaveEnabled = false; body.addView(this) }
                button("保存播放设置") {
                    runCatching { ParentPlaybackSettings(volume.text.toString().toInt(), rate.text.toString().toInt(),
                        duration.text.toString().toInt()) }.onSuccess(model::saveExecutionSettings)
                        .onFailure { label("请检查音量0–100、语速85–115、时长60–600。") }
                }
                if (!model.hasSavedConnection) {
                    if (connectionPreset() != null)
                        button("连接瓦力") { model.requestSystemOwner(OwnerOperation.PROVISION_ENDPOINT) }
                    else label("此安装包尚未提供本机连接，请联系安装管理员。")
                }

                button("帮助与反馈") { model.navigate(PanelMode.FEEDBACK) }
            }
            PanelMode.CONNECTION -> {
                val preset = connectionPreset()
                if (model.hasSavedConnection) label("本机连接已保存，无需重复设置。")
                else if (preset == null) label("此安装包尚未提供本机连接，请联系安装管理员。")
                else {
                    label("使用本机已准备好的连接。确认后保存，无需填写其他信息。")
                    button("确认连接") { model.importConnection(preset.address, preset.tokenChars(), preset.user) }
                }

            }
            PanelMode.FEEDBACK -> label("管理页面已失效，请退出后重新进入。")
            PanelMode.UNAVAILABLE -> label("管理设置暂不可用。不会清除或重建已有配对和安全存储。")
        }
        button(if (state.mode == PanelMode.SETTINGS) "退出管理" else "取消", true) { model.exit() }
        activity.setContentView(ScrollView(activity).apply { isSaveEnabled = false; addView(body) })
    }
    private fun notice(reason: PanelNotice) = when (reason) {
        PanelNotice.NONE -> "管理设置"
        PanelNotice.LOADING -> "正在读取安全设置…"
        PanelNotice.UNCONFIGURED, PanelNotice.UNOWNED -> "本机管理设置暂不可用。"
        PanelNotice.PIN_FORMAT, PanelNotice.WRONG_PIN, PanelNotice.COOLDOWN -> "管理页面已失效，请重新进入。"
        PanelNotice.LOCKED -> if (model.directManagement) "本次管理已结束，请退出后长按右下角重新进入。" else "已锁定，请重新验证。"
        PanelNotice.STORAGE -> "安全设置暂不可用。请退出后稍后再试。"
        PanelNotice.SAVED -> "已保存本地上限。"
        PanelNotice.INVALID_LIMIT -> "请输入 0 到 100 的整数。"
        PanelNotice.PIN_MISMATCH, PanelNotice.PIN_CHANGED, PanelNotice.RECOVERY_UNAVAILABLE,
        PanelNotice.OWNER_READY, PanelNotice.OWNER_UNAVAILABLE -> "管理页面已失效，请重新进入。"
        PanelNotice.FEEDBACK_UNAVAILABLE -> "帮助与反馈暂不可用，请退出后重新进入管理。"
        PanelNotice.CONNECTION_SAVED -> "连接已保存；远端有效性将在连接时核验。"
    }
}
