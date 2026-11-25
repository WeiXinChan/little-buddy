package com.littlebuddy.v2.parent

import java.util.concurrent.atomic.AtomicReference

internal class ParentCommitRejected : IllegalStateException("parent authorization revoked")

/** Lifecycle invalidation and final commit decisions compete on the SAME atomic cell.
 * claim is called only after staging IO, at the final publication boundary. A successful CAS
 * is tentative until its post-CAS deadline witness accepts it. For accepted claims, that CAS
 * is the logical decision: physical publication/readback may follow and fail,
 * in which case the domain quarantines and never reports success. Revoke never waits for IO.
 * A revoke winning before claim rejects the staged write; winning after claim cannot undo an
 * already decided transaction but immediately rejects every later old-epoch operation. */
internal class ParentEpoch {
    private class Stamp(val page: Long)
    private val stamp = AtomicReference(Stamp(0))
    fun current() = stamp.get().page
    fun revoke(): Long = stamp.updateAndGet { Stamp(it.page + 1) }.page
    fun revokeIf(page: Long) {
        while (true) {
            val before = stamp.get()
            if (before.page != page || stamp.compareAndSet(before, Stamp(page + 1))) return
        }
    }
    fun claim(page: Long): Boolean {
        val before = stamp.get()
        return before.page == page && stamp.compareAndSet(before, Stamp(page))
    }
    fun advance(page: Long): Long? {
        val before = stamp.get()
        return if (before.page == page && stamp.compareAndSet(before, Stamp(page + 1))) page + 1 else null
    }
}

/** Early checks do not commit. Exactly the final publication callback calls claim().
 * Stores must stage all controllable precommit IO first, then claim, then publish once.
 * Bounded callers supply confirm: a monotonic post-CAS sample certifies the earlier CAS;
 * an expired sample rejects conservatively. Rejection is terminal, never committed.
 * A store omitting claim or failing after it must not return success. */
internal class ParentCommit(private val allowed: () -> Boolean,
                            private val decide: () -> Boolean = allowed,
                            private val confirm: () -> Boolean = { true }) {
    var committed = false; private set
    private var rejected = false
    private fun reject(): Nothing { rejected = true; throw ParentCommitRejected() }
    fun checkAllowed() { if (rejected || !committed && !allowed()) reject() }
    fun claim(): Boolean {
        if (rejected) reject()
        if (!committed) {
            if (!decide()) reject()
            // A monotonic post-CAS sample can certify that the earlier CAS was in time.
            // No committed flag or physical publication is allowed before confirmation.
            if (!confirm()) reject()
            committed = true
        }
        return true
    }
}
