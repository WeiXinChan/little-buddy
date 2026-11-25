package com.littlebuddy.v2.parent

/** Main/UI-thread owner, including synchronous factory/presentation/disposal reentry.
 * A factory transfers its returned handle exclusively to this slot. Partial construction which
 * throws before returning remains the factory's responsibility. Retired handles never resume.
 */
internal class ParentRouteSlot<T>(private val pausePage: (T) -> Unit,
    private val closePage: (T) -> Unit) {
    private class Owner<T>(val ticket: Long) {
        var ready = false
        var page: T? = null
    }
    private var owner: Owner<T>? = null
    private fun dispose(page: T) { runCatching { closePage(page) } }
    private fun retire(old: Owner<T>?) {
        val page = old?.page
        old?.page = null // detach before user cleanup can reenter
        if (page != null) dispose(page)
    }
    private fun obtain(ticket: Long, factory: () -> T?): Owner<T> {
        owner?.let { if (it.ticket == ticket) return it }
        val next = Owner<T>(ticket)
        val old = owner
        owner = next // reserve before old disposal; a later reentrant request wins
        retire(old)
        if (owner !== next) return next
        val result = runCatching(factory).getOrNull()
        if (owner === next) {
            next.page = result
            next.ready = true
        } else if (result != null) {
            dispose(result) // local, unpublished result only; never touch the replacement owner
        }
        return next
    }
    fun show(ticket: Long, factory: () -> T?): T? {
        val current = obtain(ticket, factory)
        return if (owner === current && current.ready) current.page else null
    }
    /** Same-ticket recursion while constructing waits for the outer call, not a false failure. */
    fun mount(ticket: Long, factory: () -> T?, present: (T) -> Unit, failed: () -> Unit) {
        val current = obtain(ticket, factory)
        if (owner !== current || !current.ready) return
        val page = current.page
        if (page == null) { failed(); return }
        try { present(page) } catch (_: Exception) {
            if (owner === current) failed()
        }
    }
    fun close(ticket: Long) { if (owner?.ticket == ticket) close() }
    fun pause() { owner?.page?.let { runCatching { pausePage(it) } } }
    fun close() {
        val old = owner
        owner = null
        retire(old)
    }
}
