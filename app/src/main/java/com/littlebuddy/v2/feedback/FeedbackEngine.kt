package com.littlebuddy.v2.feedback

import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

internal fun interface FeedbackQueue { fun post(action: () -> Unit) }
internal sealed class FeedbackScreen {
    class Issues(val items: List<FeedbackView>, val available: Boolean) : FeedbackScreen()
    class Preview(val category: Category, val description: String, val logs: LogPreview, val available: Boolean) : FeedbackScreen()
    class Detail(val item: FeedbackView) : FeedbackScreen()
    class Editor(val message: String = "") : FeedbackScreen()
    class Notice(val failure: Failure) : FeedbackScreen()
    object Locked : FeedbackScreen()
}

/** Exactly one serial worker owns one vault/core, independently of page lifetime. */
internal class FeedbackEngine(private val queue: FeedbackQueue, private val ui: FeedbackQueue,
    private val makeCore: (ParentAuthorizer) -> FeedbackCore,
    private val available: () -> Boolean = { false }) {
    private val router = FeedbackSessionRouter()
    private var core: FeedbackCore? = null // worker only
    private val page = AtomicReference<FeedbackController?>()
    private fun core() = core ?: makeCore(router).also { core = it }
    fun open(authority: FeedbackPageAuthority, render: (FeedbackScreen) -> Unit): FeedbackController {
        val next = FeedbackController(this, authority, render)
        router.install(authority)
        page.getAndSet(next)?.retire()
        next.showList()
        return next
    }
    fun current(controller: FeedbackController) = page.get() === controller && router.current(controller.authority)
    fun close(controller: FeedbackController) {
        router.close(controller.authority)
        if (page.compareAndSet(controller, null)) queue.post { if (page.get() == null) core?.cancelDraft() }
    }
    fun run(controller: FeedbackController, version: Long, action: (FeedbackCore) -> FeedbackScreen) {
        queue.post {
            if (!controller.matches(version)) return@post
            if (!current(controller)) {
                ui.post { if (controller.matches(version)) controller.pause() }
                return@post
            }
            val screen = try { router.asPage(controller.authority) { action(core()) } }
            catch (error: FeedbackFailure) { FeedbackScreen.Notice(error.reason) }
            catch (_: Exception) { FeedbackScreen.Notice(Failure.STORAGE) }
            ui.post {
                if (controller.matches(version)) {
                    if (current(controller)) controller.deliver(screen) else controller.pause()
                }
            }
        }
    }
    /** Scheduled worker path: no PIN, no parent page, no new submit capability. */
    fun sweep(done: (Boolean) -> Unit = {}) {
        queue.post {
            val success = try {
                val value = core(); value.sweep(); value.drainDeletions()
                val active = page.get()
                if (active != null) {
                    if (current(active)) router.asPage(active.authority) { active.afterSweep(value) }
                    else ui.post { if (page.get() === active) active.pause() }
                }
                true
            } catch (_: Exception) { false }
            if (!success) page.get()?.let { active -> ui.post { if (page.get() === active) active.deliver(FeedbackScreen.Notice(Failure.STORAGE)) } }
            done(success)
        }
    }
    fun providerAvailable() = available()
}

internal class FeedbackController(private val engine: FeedbackEngine, internal val authority: FeedbackPageAuthority,
    render: (FeedbackScreen) -> Unit) {
    private val version = AtomicLong(0)
    @Volatile private var sink: ((FeedbackScreen) -> Unit)? = render
    private var token: Confirmation? = null // worker only
    fun matches(value: Long) = value == version.get() && sink != null
    internal fun deliver(screen: FeedbackScreen) { sink?.invoke(screen) }
    private fun action(invalidate: Boolean = true, work: (FeedbackCore) -> FeedbackScreen) {
        if (invalidate) authority.invalidate()
        val requested = version.incrementAndGet()
        engine.run(this, requested, work)
    }
    fun showList() = action { value ->
        token = null; value.cancelDraft()
        FeedbackScreen.Issues(value.list(), engine.providerAvailable())
    }
    fun edit() = action { value -> token = null; value.cancelDraft(); FeedbackScreen.Editor() }
    fun preview(category: Category, description: String, from: Long?, through: Long?) = action { value ->
        value.startDraft(category, description)
        if ((from == null) != (through == null)) throw FeedbackFailure(Failure.INVALID)
        if (from != null && through != null) value.selectLogs(from, through)
        val confirmation = value.preview(); token = confirmation
        FeedbackScreen.Preview(category, description, confirmation.logs, engine.providerAvailable())
    }
    fun submit() = action(false) { value ->
        val confirmation = token ?: throw FeedbackFailure(Failure.STALE)
        value.submit(confirmation); token = null
        FeedbackScreen.Issues(value.list(), engine.providerAvailable())
    }
    fun detail(id: String) = action { value ->
        token = null; value.cancelDraft()
        FeedbackScreen.Detail(value.list().find { it.id == id } ?: throw FeedbackFailure(Failure.STALE))
    }
    fun withdraw(id: String) = action { value ->
        token = null; value.withdraw(id); value.drainDeletions()
        FeedbackScreen.Issues(value.list(), engine.providerAvailable())
    }
    fun clearLocal(id: String) = action { value ->
        token = null; value.clearLocalMaterial(id)
        FeedbackScreen.Issues(value.list(), engine.providerAvailable())
    }
    fun clearLogs() = action { value ->
        token = null; value.clearLogs()
        FeedbackScreen.Issues(value.list(), engine.providerAvailable())
    }
    internal fun afterSweep(value: FeedbackCore) {
        val previous = token ?: return
        if (!value.confirmationCurrent(previous)) {
            token = null
            // Post using the SAME presentation epoch: a later user edit must not be overwritten.
            val requested = version.get()
            engine.run(this, requested) { FeedbackScreen.Editor("选定日志已到期，请重新预览确认。") }
        }
    }
    fun pause() {
        version.incrementAndGet(); authority.close()
        deliver(FeedbackScreen.Locked); engine.close(this)
    }
    fun close() { pause(); sink = null }
    internal fun retire() { version.incrementAndGet(); authority.close(); deliver(FeedbackScreen.Locked); sink = null }
}
