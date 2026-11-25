package com.littlebuddy.v2.feedback

import com.littlebuddy.v2.parent.ParentDomain
import java.util.concurrent.atomic.AtomicReference

/** M08 owns the implementation, delegating only to domain.acceptProtected(grant, decision).
 * A missing host adapter refuses every decision; early read checks are never commit permission. */
internal fun interface FeedbackGrantGate {
    fun accept(domain: ParentDomain, grant: ParentDomain.Grant, decision: () -> Unit): Boolean
}
internal object DenyFeedbackGrantGate : FeedbackGrantGate {
    override fun accept(domain: ParentDomain, grant: ParentDomain.Grant, decision: () -> Unit) = false
}
internal interface FeedbackPageAuthority : ParentAuthorizer {
    fun current(): Boolean
    fun close()
    fun invalidate()
}
internal class ParentFeedbackAuthorizer(private val domain: ParentDomain,
    private val grant: ParentDomain.Grant, private val gate: FeedbackGrantGate) : FeedbackPageAuthority {
    private class Epoch
    private val epoch = AtomicReference<Epoch?>(Epoch())
    private class Intent(val owner: ParentFeedbackAuthorizer, val epoch: Epoch,
        val operation: Operation, val scope: String) : ParentIntent { var used = false }
    override fun current() = epoch.get() != null && domain.volumeLimit(grant) != null
    override fun prepare(operation: Operation, digest: String): ParentIntent? {
        val page = epoch.get() ?: return null
        if (!current()) return null
        return Intent(this, page, operation, digest)
    }
    override fun accept(intent: ParentIntent, operation: Operation, digest: String, acceptance: () -> Unit): Boolean {
        val value = intent as? Intent ?: return false
        if (value.owner !== this || value.operation != operation || value.scope != digest) return false
        var decided = false
        gate.accept(domain, grant) {
            synchronized(value) {
                // No IO: local page closure and this one-shot decision race on the same cell.
                if (!value.used && epoch.compareAndSet(value.epoch, value.epoch)) {
                    value.used = true
                    acceptance(); decided = true
                }
            }
        }
        return decided
    }
    override fun invalidate() { epoch.updateAndGet { if (it == null) null else Epoch() } }
    override fun close() { epoch.set(null) } // Never domain.revoke(): an old handle must not revoke a newer route.
}

/** A pending operation keeps its ORIGINAL page owner, even when a new page is installed. */
internal class FeedbackSessionRouter : ParentAuthorizer {
    private class Routed(val owner: FeedbackPageAuthority, val inner: ParentIntent) : ParentIntent
    private val active = AtomicReference<FeedbackPageAuthority?>()
    private val caller = ThreadLocal<FeedbackPageAuthority>()
    fun <T> asPage(authority: FeedbackPageAuthority, action: () -> T): T {
        caller.set(authority)
        return try { action() } finally { caller.remove() }
    }
    fun install(authority: FeedbackPageAuthority) { active.getAndSet(authority)?.close() }
    fun current(authority: FeedbackPageAuthority) = active.get() === authority && authority.current()
    fun close(authority: FeedbackPageAuthority) {
        authority.close(); active.compareAndSet(authority, null)
    }
    override fun prepare(operation: Operation, digest: String): ParentIntent? {
        val owner = active.get() ?: return null
        if (caller.get() !== owner) return null
        return owner.prepare(operation, digest)?.let { Routed(owner, it) }
    }
    override fun accept(intent: ParentIntent, operation: Operation, digest: String, acceptance: () -> Unit): Boolean {
        val value = intent as? Routed ?: return false
        if (active.get() !== value.owner) return false
        var published = false
        val accepted = value.owner.accept(value.inner, operation, digest) {
            if (active.compareAndSet(value.owner, value.owner)) { acceptance(); published = true }
        }
        return accepted && published
    }
}
