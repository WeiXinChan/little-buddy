package com.littlebuddy.v2.parent

import android.app.Activity
import android.text.InputFilter
import android.text.InputType
import android.text.TextUtils
import android.text.method.DigitsKeyListener
import android.text.method.PasswordTransformationMethod
import android.view.ActionMode
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/** Actual native widgets. No PIN String, saved input, autofill, suggestions or clipboard import. */
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
        label(when (state.mode) {
            PanelMode.VERIFY -> "家长验证"
            PanelMode.CHANGE_PIN -> "修改 PIN"
            else -> "家长管理"
        }, 26f)
        if (state.mode == PanelMode.SETTINGS) label(if (model.hasSavedConnection) "本机连接已保存" else "尚未连接",14f)
        if (state.mode == PanelMode.SETTINGS && model.hasSavedConnection) label(connectionNotice(),14f)
        label(if (state.notice == PanelNotice.NONE && state.mode == PanelMode.SETTINGS)
            "已验证。退出或闲置后会锁定。" else notice(state.notice))
        when (state.mode) {
            PanelMode.VERIFY -> {
                val pin = pin(body, "6 位 PIN").apply { isEnabled = !state.busy && state.notice != PanelNotice.COOLDOWN }
                button("验证", !state.busy && state.notice != PanelNotice.COOLDOWN) { model.verify(take(pin)) }
                button("忘记 PIN") { model.recoveryHelp() }
            }
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
                button("修改 PIN") { model.navigate(PanelMode.CHANGE_PIN) }
                button("帮助与反馈") { model.navigate(PanelMode.FEEDBACK) }
            }
            PanelMode.CHANGE_PIN -> {
                val first = pin(body, "新 6 位 PIN").apply { isEnabled = !state.busy }
                val repeated = pin(body, "再输入一次").apply { isEnabled = !state.busy }
                label("保存后请使用新 PIN 重新验证。")
                button("保存新 PIN") { model.changePin(take(first), take(repeated)) }
                button("返回管理") { model.navigate(PanelMode.SETTINGS) }
            }
            PanelMode.OWNER_PIN -> {
                label("系统验证已完成，请设置家长 PIN。")
                val first = pin(body, "新6位PIN"); val second = pin(body, "再次输入")
                button("保存 PIN") { model.setOwnerPin(take(first), take(second)) }
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
            PanelMode.FEEDBACK -> label("家长授权已失效，请返回重新验证。")
            PanelMode.UNAVAILABLE -> {
                if (state.notice == PanelNotice.UNOWNED) {
                    label("首次使用请先完成系统验证，再设置家长 PIN。")
                    button("系统验证并初始化 PIN") { model.requestSystemOwner(OwnerOperation.INITIALIZE_PIN) }
                } else label("需安全锁屏与可用系统认证；Android 8–10还需已登记的硬件指纹。旧密钥/记录异常不会自动重建。")
            }
        }
        button(if (state.mode == PanelMode.SETTINGS) "退出管理" else "取消", true) { model.exit() }
        activity.setContentView(ScrollView(activity).apply { isSaveEnabled = false; addView(body) })
    }
    private fun pin(body: LinearLayout, hint: String) = EditText(activity).apply {
        this.hint = hint; inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_VARIATION_PASSWORD
        keyListener = DigitsKeyListener.getInstance("0123456789")
        setRawInputType(InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_VARIATION_PASSWORD)
        transformationMethod = PasswordTransformationMethod.getInstance()
        filters = arrayOf(InputFilter.LengthFilter(6)); isSingleLine = true; isSaveEnabled = false
        isLongClickable = false; setTextIsSelectable(false)
        importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
        imeOptions = EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING or EditorInfo.IME_ACTION_DONE
        val noSelection = object : ActionMode.Callback {
            override fun onCreateActionMode(mode: ActionMode, menu: Menu) = false
            override fun onPrepareActionMode(mode: ActionMode, menu: Menu) = false
            override fun onActionItemClicked(mode: ActionMode, item: MenuItem) = false
            override fun onDestroyActionMode(mode: ActionMode) {}
        }
        customSelectionActionModeCallback = noSelection
        customInsertionActionModeCallback = noSelection
        inputs.add(this); body.addView(this)
    }
    private fun take(field: EditText): CharArray {
        val text = field.text
        return CharArray(text.length).also { TextUtils.getChars(text, 0, text.length, it, 0); text.clear() }
    }
    private fun notice(reason: PanelNotice) = when (reason) {
        PanelNotice.NONE -> "请输入屏幕 PIN；语音不能代替验证。"
        PanelNotice.LOADING -> "正在读取安全设置…"
        PanelNotice.UNCONFIGURED -> "本机系统认证暂不可用，请检查安全锁屏和兼容能力。"
        PanelNotice.UNOWNED -> "尚未设置本机家长PIN，请先通过系统认证再初始化。"
        PanelNotice.PIN_FORMAT -> "请输入 6 位数字。"
        PanelNotice.WRONG_PIN -> "PIN 不正确。"
        PanelNotice.COOLDOWN -> "尝试次数过多，请稍后再试。"
        PanelNotice.LOCKED -> "已锁定，请重新验证。"
        PanelNotice.STORAGE -> "安全设置暂不可用。请退出后稍后再试。"
        PanelNotice.SAVED -> "已保存本地上限。"
        PanelNotice.INVALID_LIMIT -> "请输入 0 到 100 的整数。"
        PanelNotice.PIN_MISMATCH -> "两次 PIN 须一致，且都是 6 位数字。"
        PanelNotice.PIN_CHANGED -> "PIN 已更新，请用新 PIN 验证。"
        PanelNotice.RECOVERY_UNAVAILABLE -> "安全恢复尚不可用，不会清除配对或重置 PIN。"
        PanelNotice.FEEDBACK_UNAVAILABLE -> "帮助与反馈暂不可用，请重新验证后再试。"
        PanelNotice.OWNER_READY -> "系统验证仅本次有效，请在一分钟内完成；取消不会改配对或PIN。"
        PanelNotice.OWNER_UNAVAILABLE -> "系统授权未完成或已过期，请重新验证。不会自动重置。"
        PanelNotice.CONNECTION_SAVED -> "连接已保存，请用PIN重新验证；远端有效性将在连接时核验。"
    }
}
