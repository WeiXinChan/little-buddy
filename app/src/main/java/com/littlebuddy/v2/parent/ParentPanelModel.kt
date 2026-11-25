package com.littlebuddy.v2.parent

import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

internal enum class PanelMode { VERIFY, SETTINGS, CHANGE_PIN, FEEDBACK, UNAVAILABLE }
internal enum class PanelNotice { NONE, LOADING, UNCONFIGURED, UNOWNED, PIN_FORMAT, WRONG_PIN,
    COOLDOWN, LOCKED, STORAGE, SAVED, INVALID_LIMIT, PIN_MISMATCH, PIN_CHANGED, RECOVERY_UNAVAILABLE,
    FEEDBACK_UNAVAILABLE }
internal data class PanelState(val mode: PanelMode, val notice: PanelNotice = PanelNotice.NONE,
                              val busy: Boolean = false, val volume: Int? = null)
internal class ParentRouteSession(val domain: ParentDomain, val grant: ParentDomain.Grant, val revision: Long)

/** Activity owns main/UI calls; work and UI queues are explicit. No accepted Boolean is authority.
 * Every asynchronous result is page/revision guarded, every write uses the actual Grant again.
 * load runs on the worker. Production loader has no binding until reviewed D04 provisioning.
 */
internal class ParentPanelModel(private val load: () -> ParentDomain?,
    private val work: (() -> Unit) -> Unit, private val ui: (() -> Unit) -> Unit,
    private val render: (PanelState) -> Unit, private val leave: () -> Unit) {
    private val domain = AtomicReference<ParentDomain?>()
    private val revision = AtomicLong()
    private val viewRevision = AtomicLong()
    private val pending = ConcurrentHashMap.newKeySet<CharArray>()
    @Volatile private var active = false
    private var page = -1L
    private var grant: ParentDomain.Grant? = null
    var state = PanelState(PanelMode.VERIFY); private set
    val viewToken get() = viewRevision.get()
    fun userAction(token: Long, action: () -> Unit): Boolean {
        if (!active || token != viewRevision.get()) return false
        action(); return true
    }
    private fun show(value: PanelState) { state = value; viewRevision.incrementAndGet(); render(value) }
    private fun live(ticket: Long) = active && revision.get() == ticket

    fun open() {
        invalidate()
        active = true
        val ticket = revision.get()
        show(PanelState(PanelMode.VERIFY, PanelNotice.LOADING, true))
        work {
            if (!live(ticket)) return@work
            val result = runCatching { domain.get() ?: load() }
            result.getOrNull()?.let { domain.compareAndSet(null, it) }
            ui {
                if (!live(ticket)) return@ui
                val d = result.getOrNull()
                if (d == null) show(PanelState(PanelMode.UNAVAILABLE,
                    if (result.isFailure) PanelNotice.STORAGE else PanelNotice.UNCONFIGURED))
                else { page = d.enterPage(); locked(d) }
            }
        }
    }
    /** Synchronous lifecycle first step: revoke before any worker, page callback or IO cleanup. */
    private fun invalidate() {
        active = false; revision.incrementAndGet()
        if (page >= 0) domain.get()?.invalidatePage(page)
        page = -1L
        grant = null; pending.forEach { it.fill('\u0000') }; pending.clear()
    }
    fun pause(afterInvalidate: () -> Unit = {}) {
        invalidate(); afterInvalidate(); show(PanelState(PanelMode.VERIFY, PanelNotice.LOCKED))
    }
    fun close() { invalidate() }
    fun exit() { invalidate(); leave() }
    private fun locked(d: ParentDomain, notice: PanelNotice? = null) {
        grant = null
        val reason = when (d.state()) {
            ParentDomain.State.UNOWNED -> PanelNotice.UNOWNED
            ParentDomain.State.COOLDOWN -> PanelNotice.COOLDOWN
            ParentDomain.State.QUARANTINED -> PanelNotice.STORAGE
            else -> notice ?: PanelNotice.NONE
        }
        show(PanelState(if (reason == PanelNotice.UNOWNED || reason == PanelNotice.STORAGE)
            PanelMode.UNAVAILABLE else PanelMode.VERIFY, reason))
    }
    private fun lock(d: ParentDomain) {
        revision.incrementAndGet(); if (page >= 0) d.invalidatePage(page); grant = null
        pending.forEach { it.fill('\u0000') }; pending.clear()
        page = -1L; locked(d, PanelNotice.LOCKED)
    }
    fun localTouch() {
        val d = domain.get() ?: return
        val current = grant ?: return
        if (!d.localAction(current)) lock(d)
    }
    /** Timer/heartbeat never calls localTouch. No automatic authorization after focus returns. */
    fun tick() {
        if (!active) return
        val d = domain.get() ?: return
        val current = grant
        if (current != null && !d.isAuthorized(current)) lock(d)
        else if (current == null && !state.busy && state.notice == PanelNotice.COOLDOWN &&
            d.state() != ParentDomain.State.COOLDOWN) locked(d)
    }
    fun verify(pin: CharArray) {
        val d = domain.get()
        if (!active || state.busy || state.mode != PanelMode.VERIFY || d == null) { pin.fill('\u0000'); return }
        if (!validPin(pin)) { pin.fill('\u0000'); show(state.copy(notice = PanelNotice.PIN_FORMAT)); return }
        page = d.enterPage() // Only an explicit current-page PIN attempt starts a new auth epoch.
        val ticket = revision.incrementAndGet(); val epoch = page
        pending.add(pin); show(state.copy(busy = true, notice = PanelNotice.NONE))
        work {
            val result = try { if (live(ticket)) d.verify(pin, epoch) else null }
                catch (_: Exception) { null } finally { pin.fill('\u0000'); pending.remove(pin) }
            ui {
                if (!live(ticket)) { result?.let(d::revokePage); return@ui }
                if (result != null && d.isAuthorized(result)) {
                    grant = result; show(PanelState(PanelMode.SETTINGS, volume = d.volumeLimit(result)))
                } else locked(d, when (d.state()) {
                    ParentDomain.State.COOLDOWN -> PanelNotice.COOLDOWN
                    ParentDomain.State.QUARANTINED -> PanelNotice.STORAGE
                    else -> PanelNotice.WRONG_PIN
                })
            }
        }
    }
    fun saveVolume(value: Int) {
        val d = domain.get() ?: return; val current = grant ?: return
        if (!active || state.busy || state.mode != PanelMode.SETTINGS) return
        if (value !in 0..100) { show(state.copy(notice = PanelNotice.INVALID_LIMIT)); return }
        if (!d.localAction(current)) { lock(d); return }
        val ticket = revision.get(); show(state.copy(busy = true, notice = PanelNotice.NONE))
        work {
            val saved = live(ticket) && runCatching { d.saveVolumeLimit(current, value) }.getOrDefault(false)
            ui {
                if (!live(ticket)) return@ui
                if (!d.isAuthorized(current)) lock(d)
                else show(PanelState(PanelMode.SETTINGS, if (saved) PanelNotice.SAVED else PanelNotice.STORAGE,
                    volume = d.volumeLimit(current)))
            }
        }
    }
    fun navigate(mode: PanelMode, localInput: Boolean = true): ParentRouteSession? {
        val d = domain.get() ?: return null; val current = grant ?: return null
        if (!active || state.busy || mode !in setOf(PanelMode.SETTINGS, PanelMode.CHANGE_PIN, PanelMode.FEEDBACK)) return null
        if (!(if (localInput) d.localAction(current) else d.isAuthorized(current))) { lock(d); return null }
        val next = d.nextPage(current) ?: run { lock(d); return null }
        grant = next; page = next.pageEpoch
        val ticket = revision.incrementAndGet()
        show(PanelState(mode, volume = d.volumeLimit(next)))
        return ParentRouteSession(d, next, ticket)
    }
    fun currentRoute(): ParentRouteSession? {
        val d = domain.get() ?: return null; val current = grant ?: return null
        return if (active && state.mode == PanelMode.FEEDBACK && d.isAuthorized(current))
            ParentRouteSession(d, current, revision.get()) else null
    }
    fun routeExit(ticket: Long, unavailable: Boolean = false) {
        if (!live(ticket) || state.mode != PanelMode.FEEDBACK) return
        navigate(PanelMode.SETTINGS, localInput = false)
        if (state.mode == PanelMode.SETTINGS && unavailable) show(state.copy(notice = PanelNotice.FEEDBACK_UNAVAILABLE))
    }
    fun changePin(pin: CharArray, repeated: CharArray) {
        val d = domain.get(); val current = grant
        if (!active || state.busy || state.mode != PanelMode.CHANGE_PIN || d == null || current == null) {
            pin.fill('\u0000'); repeated.fill('\u0000'); return
        }
        if (!validPin(pin) || !validPin(repeated) || !pin.contentEquals(repeated)) {
            pin.fill('\u0000'); repeated.fill('\u0000'); show(state.copy(notice = PanelNotice.PIN_MISMATCH)); return
        }
        repeated.fill('\u0000')
        if (!d.localAction(current)) { pin.fill('\u0000'); lock(d); return }
        val ticket = revision.get(); pending.add(pin); show(state.copy(busy = true, notice = PanelNotice.NONE))
        work {
            val changed = try { live(ticket) && d.changePin(current, pin) }
                catch (_: Exception) { false } finally { pin.fill('\u0000'); pending.remove(pin) }
            ui {
                if (!live(ticket)) return@ui
                grant = null; page = -1L
                locked(d, if (changed) PanelNotice.PIN_CHANGED else PanelNotice.LOCKED)
            }
        }
    }
    fun recoveryHelp() {
        if (active && !state.busy) show(state.copy(notice = PanelNotice.RECOVERY_UNAVAILABLE))
    }
    companion object { private fun validPin(pin: CharArray) = pin.size == 6 && pin.all { it in '0'..'9' } }
}
