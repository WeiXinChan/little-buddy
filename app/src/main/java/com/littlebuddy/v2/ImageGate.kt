package com.littlebuddy.v2

internal data class ImageScope(val session: String, val turn: Long, val epoch: Long, val revision: Long)
internal data class ImageAsset(val id: String, val sha256: String, val width: Int, val height: Int)
internal data class ImageReady(val scope: ImageScope, val topic: Int, val token: String, val asset: ImageAsset)
internal data class ImageReveal(val ready: ImageReady, val player: String, val stream: Int, val segment: String, val end: Long)
internal interface ImagePort {
    fun bind(scope: ImageScope)
    fun ready(value: ImageReady)
    fun reveal(value: ImageReveal)
    fun acknowledged(player: String, stream: Int, segment: String, end: Long)
    fun clear()
}

/** Single private slot. The lock covers memory decisions/render only, never asset IO.
 * Every asynchronous publication rechecks the same ticket; clear revokes it before notifying UI.
 */
internal class ImageGate<T>(private val changed: () -> Unit) {
    private var scope: ImageScope? = null
    private var serial = 0L
    private var prepared: ImageReady? = null
    private var loaded: T? = null
    private var revealed = false
    private val acks = LinkedHashSet<List<Any>>()
    private val tokens = HashSet<String>()
    @Synchronized fun bind(value: ImageScope) {
        if (value == scope) return
        clear(); scope = value
    }
    @Synchronized fun clear() {
        serial++; scope = null; prepared = null; loaded = null; revealed = false; acks.clear(); tokens.clear(); changed()
    }
    /** Future topic is deliberately not compared with a currently displayed topic. */
    @Synchronized fun prepare(value: ImageReady): Long? {
        if (value.scope != scope || value.topic < 0 ||
            !value.token.matches(Regex("[a-f0-9]{32}"))) return null
        if (tokens.size >= 256 || !tokens.add(value.token)) return null // one use, including after replacement/failure
        serial++; prepared = value; loaded = null; revealed = false; changed(); return serial
    }
    @Synchronized fun loaded(ticket: Long, value: T) {
        if (ticket != serial || prepared == null || prepared?.scope != scope) return
        loaded = value; if (revealed) changed()
    }
    @Synchronized fun failed(ticket: Long) {
        if (ticket != serial) return
        serial++; prepared = null; loaded = null; revealed = false; changed()
    }
    @Synchronized fun acknowledged(player: String, stream: Int, segment: String, end: Long) {
        if (scope == null) return
        if (acks.size == 128) acks.remove(acks.first())
        acks.add(listOf(player, stream, segment, end))
    }
    @Synchronized fun reveal(value: ImageReveal): Boolean {
        if (revealed || value.ready != prepared || value.ready.scope != scope ||
            listOf(value.player, value.stream, value.segment, value.end) !in acks) return false
        revealed = true; changed(); return true
    }
    /** The UI calls this again on its own thread, immediately before actual publication. */
    @Synchronized fun render(draw: (T?) -> Unit) { draw(if (revealed && prepared?.scope == scope) loaded else null) }
}
