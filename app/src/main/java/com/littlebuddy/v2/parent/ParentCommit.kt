package com.littlebuddy.v2.parent

import java.util.concurrent.atomic.AtomicReference

internal class ParentCommitRejected : IllegalStateException("parent authorization revoked")

/** Lifecycle invalidation and final commit decisions compete on the SAME atomic cell.
 * claim is called only after staging IO, at the final publication boundary. A successful CAS
 * is the irrevocable logical decision: physical publication/readback may follow and fail,
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
}

/** Early checks do not commit. Exactly the final publication callback calls claim().
 * Stores must stage all controllable precommit IO first, then claim, then publish once.
 * A store omitting claim or failing after it must not return success. */
internal class ParentCommit(private val allowed: () -> Boolean,
                            private val decide: () -> Boolean = allowed) {
    var committed = false; private set
    fun checkAllowed() { if (!committed && !allowed()) throw ParentCommitRejected() }
    fun claim(): Boolean {
        if (!committed) {
            if (!decide()) throw ParentCommitRejected()
            committed = true
        }
        return true
    }
}
