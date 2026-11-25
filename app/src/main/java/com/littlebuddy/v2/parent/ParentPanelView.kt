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
    private val feedback: ParentFeedbackRoute = AndroidParentFeedbackRoute) {
    private val inputs = mutableListOf<EditText>()
    private val routes = ParentRouteSlot<ParentRoutePage>({ it.pause() }, { it.close() })
    fun pause() { clearInputs(); routes.pause() }
    fun close() { clearInputs(); routes.close() }
    private fun clearInputs() { inputs.forEach { it.text?.clear() }; inputs.clear() }
    fun render(state: PanelState) {
        clearInputs()
        val route = if (state.mode == PanelMode.FEEDBACK) model.currentRoute() else null
        if (route != null) {
            val page = routes.show(route.revision) {
                feedback.create(activity, route.domain, route.grant) {
                    activity.runOnUiThread { model.routeExit(route.revision) }
                }
            }
            if (page == null) { model.routeExit(route.revision, unavailable = true); return }
            try { activity.setContentView(page.view) }
            catch (_: Exception) { routes.close(); model.pause() }
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
                label("上限将在语音功能接通后生效。")
                button("保存上限") { model.saveVolume(volume.text.toString().toIntOrNull() ?: -1) }
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
            else -> Unit // UNAVAILABLE never offers a first-owner PIN or a recovery bypass.
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
        PanelNotice.UNCONFIGURED, PanelNotice.UNOWNED -> "家长归属尚未配置，暂不能设置或恢复 PIN。"
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
        PanelNotice.FEEDBACK_UNAVAILABLE -> "帮助与反馈尚未接通。"
    }
}
