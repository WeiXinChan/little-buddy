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
    fun pause() { page?.let { runCatching { pausePage(it) } } }
    fun close() {
        val old = page; page = null; revision = -1L
        old?.let { runCatching { closePage(it) } }
    }
}
