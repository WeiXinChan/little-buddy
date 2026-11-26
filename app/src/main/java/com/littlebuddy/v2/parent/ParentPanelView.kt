package com.littlebuddy.v2.parent

import android.app.Activity
import android.content.Intent
import android.widget.Spinner
import android.widget.ArrayAdapter
import com.littlebuddy.v2.transport.V2SshIdentity
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
    private val connectionNotice: () -> String = { "" }) {
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
        val version=activity.packageManager.getPackageInfo(activity.packageName,0)
        label("V2 ${version.versionName} · 连接状态：${connectionNotice()}",14f)
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
                button("导出V2设备SSH公钥（供管理员登记）") {
                    model.exportTransportKey({ V2SshIdentity.load(create=true).registrationKey() }) { publicKey ->
                        activity.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply {
                            type="text/plain"; putExtra(Intent.EXTRA_TEXT, publicKey)
                            putExtra(Intent.EXTRA_SUBJECT, "V2设备SSH公钥；尚须服务器登记")
                        }, "仅导出公钥"))
                    }
                }
                button("系统验证并导入连接配置") { model.requestSystemOwner(OwnerOperation.PROVISION_ENDPOINT) }
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
                label("系统验证已完成。此步骤只设置本机 PIN，不证明远程家庭账号归属。")
                val first = pin(body, "新6位PIN"); val second = pin(body, "再次输入")
                button("保存 PIN") { model.setOwnerPin(take(first), take(second)) }
            }
            PanelMode.CONNECTION -> {
                label("只导入管理员已发行的本设备 V2 地址和凭据，不在这里创建账号或令牌。TLS与候选协议核对通过后才启用儿童收音。")
                label("私有SSH只转发127.0.0.1:19483；专属账户与公钥须管理员登记。V1账户/令牌不能用于V2授权。")
                val mode=Spinner(activity).apply { adapter=ArrayAdapter(activity, android.R.layout.simple_spinner_dropdown_item,
                    arrayOf("V2私有SSH", "已发行公网直连")); body.addView(this) }
                val sshUser=EditText(activity).apply { hint="管理员发行的V2专属SSH账户"; isSaveEnabled=false; body.addView(this) }
                val address = EditText(activity).apply { hint = "wss://…/v2/voice"; isSaveEnabled = false; body.addView(this) }
                val secret = EditText(activity).apply {
                    hint = "已发行的设备连接凭据"; inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
                    transformationMethod = PasswordTransformationMethod.getInstance(); isSaveEnabled = false
                    importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
                    isLongClickable = false; filters = arrayOf(InputFilter.LengthFilter(256)); inputs.add(this); body.addView(this)
                }
                button("保存已发行的连接") { model.importConnection(if (mode.selectedItemPosition==0) "wss://127.0.0.1:19483/v2/voice" else address.text.toString(), take(secret), if (mode.selectedItemPosition==0) sshUser.text.toString() else null) }
            }
            PanelMode.FEEDBACK -> label("家长授权已失效，请返回重新验证。")
            PanelMode.UNAVAILABLE -> {
                if (state.notice == PanelNotice.UNOWNED) {
                    label("首次使用先重新验证本机系统凭据，再设置PIN；不会读取或修改其他应用配对。")
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
