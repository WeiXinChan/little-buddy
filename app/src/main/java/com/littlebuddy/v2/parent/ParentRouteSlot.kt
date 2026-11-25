package com.littlebuddy.v2.parent

/** Shared by the actual Android host and composition tests. A retired handle is never resumed.
 * Release all references even if a child throws; the binding has revoked before its cleanup.
 */
internal class ParentRouteSlot<T>(private val pausePage: (T) -> Unit,
    private val closePage: (T) -> Unit) {
    private var revision = -1L
    private var page: T? = null
    fun show(ticket: Long, factory: () -> T?): T? {
        if (ticket != revision) {
            close(); revision = ticket
            page = runCatching(factory).getOrNull()
        }
        return page
    }
    /** Actual host uses this injectable presentation boundary, including failure recovery. */
    fun mount(ticket: Long, factory: () -> T?, present: (T) -> Unit, failed: () -> Unit) {
        val current = show(ticket, factory)
        if (revision != ticket) return
        if (current == null) { failed(); return }
        try { present(current) } catch (_: Exception) { failed() }
    }
    fun close(ticket: Long) { if (revision == ticket) close() }
    fun pause() { page?.let { runCatching { pausePage(it) } } }
    fun close() {
        val old = page; page = null; revision = -1L
        old?.let { runCatching { closePage(it) } }
    }
}
