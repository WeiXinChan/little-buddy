package com.littlebuddy.v2.feedback

import android.app.Activity
import android.text.InputType
import android.view.View
import android.view.WindowManager
import android.view.inputmethod.EditorInfo
import android.widget.*
import com.littlebuddy.v2.parent.ParentDomain
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

internal interface FeedbackPageHandle {
    val view: View
    fun pause()
    fun close()
}
internal object FeedbackPageFactory {
    fun create(activity: Activity, domain: ParentDomain, grant: ParentDomain.Grant,
        gate: FeedbackGrantGate, onExit: () -> Unit): FeedbackPageHandle {
        AndroidFeedbackRuntime.configure(activity,domain)
        return AndroidFeedbackPage(activity, ParentFeedbackAuthorizer(domain, grant, gate), onExit)
    }
}

/** Native parent-only view. No Intent route, saved text state, sharing, external links or child speech. */
private class AndroidFeedbackPage(private val activity: Activity, private val authority: FeedbackPageAuthority,
    private val onExit: () -> Unit) : FeedbackPageHandle {
    private val column = LinearLayout(activity).apply { orientation = LinearLayout.VERTICAL; setPadding(24, 16, 24, 24) }
    override val view: View = ScrollView(activity).apply { addView(column); isSaveEnabled = false }
    private var description = ""
    private var category = Category.OTHER
    private var selected = false
    private var fromText = ""
    private var throughText = ""
    private val format get() = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.ROOT).apply { isLenient = false }
    private val controller: FeedbackController
    private var closed = false
    private val visibility=FeedbackVisibility(AndroidFeedbackRuntime.presentationClock())
    private val main=android.os.Handler(android.os.Looper.getMainLooper())
    private var shownUntil: Long?=null
    private val expire=object:Runnable {
        override fun run() {
            val end=shownUntil ?: return
            if(closed)return
            val time=visibility.now()
            if(!authority.current()) { pause();return }
            if(time==null || time>=end) { expireMaterial();return }
            main.postDelayed(this,minOf(500L,end-time))
        }
    }
    private fun expireMaterial() {
        scrub();begin("材料已到期或时间不可核实")
        label("正在清理本机过期副本；不会重新上传或取得新的家长授权。")
        controller.showList() // local sweep only; invalidates the old projection/confirmation immediately
    }
    private fun watch(screen:FeedbackScreen) {
        main.removeCallbacks(expire);shownUntil=visibility.until(screen)
        val end=shownUntil ?: return;val time=visibility.now() ?: return
        main.postDelayed(expire,maxOf(1L,minOf(500L,end-time)))
    }
    init {
        activity.window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        controller = AndroidFeedbackRuntime.open(activity).open(authority, ::render)
    }
    private fun begin(title: String) {
        clearViewText(column); column.removeAllViews(); label(title)
        column.isSaveEnabled = false
        column.filterTouchesWhenObscured = true
    }
    private fun label(value: String) { column.addView(TextView(activity).apply { text = value; isSaveEnabled = false; setPadding(0, 8, 0, 8) }) }
    private fun button(text: String, enabled: Boolean = true, action: () -> Unit) {
        column.addView(Button(activity).apply {
            this.text = text; isEnabled = enabled; isSaveEnabled = false; filterTouchesWhenObscured = true
            setOnClickListener { if (!closed) action() }
        })
    }
    private fun input(hint: String, text: String, multi: Boolean = false): EditText = EditText(activity).apply {
        this.hint = hint; filters = arrayOf(android.text.InputFilter.LengthFilter(if (multi) 4000 else 32))
        setText(text); isSaveEnabled = false
        importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
        inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS or
            (if (multi) InputType.TYPE_TEXT_FLAG_MULTI_LINE else 0)
        imeOptions = imeOptions or EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING
        filterTouchesWhenObscured = true
        column.addView(this)
    }
    private fun time(value: Long?) = value?.let { format.format(Date(it)) } ?: "无"
    private fun scope(value: LogPreview) {
        label("日志实际范围：${time(value.from)} 至 ${time(value.through)}（本地时间）\n${value.count} 条，${value.bytes} 字节")
    }
    private fun render(screen: FeedbackScreen) {
        if (closed) return
        if(screen!==FeedbackScreen.Locked && !authority.current()) { render(FeedbackScreen.Locked);return }
        if(!visibility.allowed(screen)) { expireMaterial();return }
        watch(screen)
        when (screen) {
            is FeedbackScreen.Issues -> {
                scrub(); begin("我提交的问题 · 仅本机")
                if (!screen.available) label("私有反馈连接未配置：不能发送或获取新回复。本机清理仍可用。")
                else label("使用已配置的自建接收端；离线状态以实际回执为准，没有固定人工回复时限。")
                if (!AndroidFeedbackRuntime.jobScheduled) label("后台清理调度未成功；应用运行和访问时仍检查到期。")
                if (screen.items.isEmpty()) label("本机没有问题材料。")
                screen.items.forEach { item -> button("${item.id}\n${state(item.state)} · 删除截止 ${time(item.deleteBy)}") { controller.detail(item.id) } }
                button("描述新问题") { description = ""; selected = false; controller.edit() }
                button("清理本机源运行日志") {
                    confirm("仅清本机源运行日志和未提交草稿的日志选择；不清已提交问题副本、PIN或配对。") { controller.clearLogs() }
                }
                button("返回管理") { close(); onExit() }
            }
            is FeedbackScreen.Editor -> {
                if (screen.message.isNotEmpty()) selected = false
                editor(screen.message)
            }
            is FeedbackScreen.Preview -> {
                begin("确认问题材料")
                label("类型：${categoryName(screen.category)}\n说明：${screen.description}")
                scope(screen.logs)
                label("仅提交本次说明及以上明确选择的日志副本，不含录音或完整聊天。源日志和副本独立到期；撤回不会清除源日志。")
                if (!screen.available) label("反馈服务未配置，当前无法发送；不会自动排队上传。")
                button("确认提交", screen.available) { controller.submit() }
                button("返回修改（原确认失效）") { controller.edit() }
                button("取消并清除草稿") { description = ""; selected = false; controller.showList() }
            }
            is FeedbackScreen.Detail -> {
                val item = screen.item
                begin("问题详情 · 仅本机")
                label("编号：${item.id}\n类型：${categoryName(item.category)}\n${state(item.state)}\n提交时间：${time(item.submittedAt)}\n删除截止：${time(item.deleteBy)}")
                label(if (item.localCleared) "本机副本已清除；这不代表服务端删除。" else item.description ?: "本机正文已撤回或到期，不可访问。")
                scope(item.logs)
                label("回复：${item.reply?.takeIf { it.isNotBlank() } ?: "暂无可用回复"}")
                button("刷新接收状态与回复", !item.localCleared && item.state !in setOf(FeedbackState.DELETED,FeedbackState.DELETING,FeedbackState.DELETE_PENDING,FeedbackState.DELETE_FAILED)) { controller.refresh(item.id) }
                button("撤回并删除整单", item.state != FeedbackState.DELETED) {
                    confirm("撤回本单说明、选定日志副本及回复；离线时仅记录删除请求。未经平台全部副本回执不会显示已删除，源日志不随之删除。") { controller.withdraw(item.id) }
                }
                button("仅清本机材料副本", !item.localCleared) {
                    confirm("仅清本机这单的说明、日志副本和回复；保留必要状态、原截止和删除任务，不清平台材料或源日志。") { controller.clearLocal(item.id) }
                }
                button("返回列表") { controller.showList() }
            }
            is FeedbackScreen.Notice -> {
                begin("操作未完成")
                label(when (screen.failure) {
                    Failure.DENIED -> "家长授权已失效，请返回管理重新验证。"
                    Failure.UNAVAILABLE -> "反馈服务未配置，未发送材料。"
                    Failure.STALE -> "材料或确认已变化，请重新预览。"
                    Failure.INVALID -> "请检查说明（最多2000字）和所选时间范围。"
                    Failure.CLOCK -> "无法确认本机时间，材料访问已暂停。"
                    Failure.QUARANTINED, Failure.STORAGE -> "本机材料存储不可用，未报告操作成功。"
                    Failure.NETWORK -> "连接或操作结果尚未确认；不会自动重发上传，也不能据此报告提交或删除成功。"
                })
                button("返回编辑") { controller.edit() }
                button("返回列表") { controller.showList() }
                button("退出") { close(); onExit() }
            }
            FeedbackScreen.Locked -> { scrub(); begin("反馈页面已锁定"); label("请返回管理重新验证。旧页面不会自动恢复。"); button("返回管理") { close(); onExit() } }
        }
    }
    private fun editor(message: String) {
        begin("描述问题")
        if (message.isNotEmpty()) label(message)
        label("请避免填写姓名、联系方式等不必要信息。不上传录音、截图或完整聊天。")
        val categories = Category.values()
        val picker = Spinner(activity).apply {
            adapter = ArrayAdapter(activity, android.R.layout.simple_spinner_dropdown_item, categories.map(::categoryName))
            setSelection(category.ordinal); isSaveEnabled = false; column.addView(this)
        }
        val body = input("家长说明（最多2000字）", description, true)
        val include = CheckBox(activity).apply { text = "主动选择必要时段的脱敏日志（默认不附带）"; isChecked = selected; isSaveEnabled = false; column.addView(this) }
        if (fromText.isEmpty()) {
            val now = System.currentTimeMillis(); fromText = time((now - 10 * 60_000).coerceAtLeast(0)); throughText = time(now)
        }
        label("时间为本地时间，格式：年-月-日 时:分:秒。只会选择范围内的现存日志。")
        val from = input("开始时间", fromText); val through = input("结束时间", throughText)
        from.isEnabled = include.isChecked; through.isEnabled = include.isChecked
        include.setOnCheckedChangeListener { _, checked -> from.isEnabled = checked; through.isEnabled = checked }
        button("预览材料与精确范围") {
            description = body.text.toString(); category = categories[picker.selectedItemPosition]; selected = include.isChecked
            fromText = from.text.toString(); throughText = through.text.toString()
            try {
                val start = if (selected) parseTime(fromText) else null
                val end = if (selected) parseTime(throughText) else null
                controller.preview(category, description, start, end)
            } catch (_: Exception) { label("时间格式无效，请按示例填写。") }
        }
        button("取消并清除草稿") { description = ""; selected = false; controller.showList() }
    }
    private fun parseTime(text: String): Long {
        val position = java.text.ParsePosition(0)
        val parsed = format.parse(text, position) ?: throw IllegalArgumentException()
        require(position.index == text.length)
        return parsed.time
    }
    private fun confirm(message: String, action: () -> Unit) {
        // Inline confirmation keeps focus in the same protected window; no dialog lifecycle bypass.
        begin("确认清理范围"); label(message)
        button("确认执行", action = action); button("取消") { controller.showList() }
    }
    private fun scrub() {
        shownUntil=null;main.removeCallbacks(expire)
        description = ""; selected = false; fromText = ""; throughText = ""
        clearViewText(column); column.removeAllViews()
    }
    private fun clearViewText(view: View) {
        if (view.hasOnClickListeners()) view.setOnClickListener(null) // release obsolete detail/reply closures
        if (view is EditText) view.text.clear()
        else if (view is TextView) view.text = ""
        if (view is android.view.ViewGroup) for (index in 0 until view.childCount) clearViewText(view.getChildAt(index))
    }
    override fun pause() { if (!closed) { scrub(); controller.pause() } }
    override fun close() { if (!closed) { scrub(); controller.close(); closed = true; column.removeAllViews() } }
    private fun categoryName(value: Category) = when(value) {
        Category.RECOGNITION -> "识别"; Category.CONVERSATION -> "接话"; Category.INTERRUPT -> "打断"
        Category.SOUND_NETWORK -> "声音/网络"; Category.IMAGE -> "图片"; Category.OTHER -> "其他"
    }
    private fun state(value: FeedbackState) = when(value) {
        FeedbackState.PENDING -> "待发送"; FeedbackState.SEND_FAILED -> "发送失败/结果未确认"
        FeedbackState.SUBMITTED -> "已提交"; FeedbackState.PROCESSING -> "处理中"; FeedbackState.REPLIED -> "已回复"
        FeedbackState.DELETE_PENDING -> "删除请求待发送"; FeedbackState.DELETING -> "正在删除"
        FeedbackState.DELETE_FAILED -> "删除未完成"; FeedbackState.DELETED -> "已确认删除"
    }
}
