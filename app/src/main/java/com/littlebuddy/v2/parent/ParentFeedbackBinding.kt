package com.littlebuddy.v2.parent

import com.littlebuddy.v2.feedback.FeedbackGrantGate
import java.util.concurrent.atomic.AtomicBoolean

/** One handle owns exactly the Grant supplied at creation. Never lends a later host's authority.
 * UI lifecycle invalidates the page before invoking child cleanup, with no wait for IO.
 * The gate publishes a short memory decision at ParentDomain's final claim, never an IO permit.
 */
internal class ParentFeedbackBinding(private val domain: ParentDomain,
    private val grant: ParentDomain.Grant) {
    private val alive = AtomicBoolean(true)
    private val closed = AtomicBoolean(false)
    val gate = FeedbackGrantGate { candidate, token, decision ->
        if (candidate !== domain || token !== grant || !alive.get()) false
        else {
            var published = false
            val accepted = domain.acceptProtected(grant) {
                if (alive.get()) { decision(); published = true }
            }
            accepted && published
        }
    }
    fun <T> build(factory: () -> T): T? {
        if (!alive.get() || !domain.isAuthorized(grant)) { invalidate(); return null }
        return try { factory() } catch (_: Exception) { invalidate(); null }
    }
    private fun invalidate() {
        alive.set(false)
        domain.revokePage(grant) // scoped: old close must never revoke the replacement route
    }
    fun pause(cleanup: () -> Unit) {
        invalidate()
        if (!closed.get()) runCatching(cleanup)
    }
    fun close(cleanup: () -> Unit) {
        invalidate()
        if (closed.compareAndSet(false, true)) runCatching(cleanup)
    }
}
