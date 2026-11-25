package com.littlebuddy.v2.parent

import org.junit.Assert.*
import org.junit.Test

class ParentRouteSlotReentryTest {
    private class Handle(val id: Int)
    private class Rig {
        val made = mutableListOf<Int>()
        val closed = mutableListOf<Int>()
        val shown = mutableListOf<Int>()
        var closing: (Handle) -> Unit = {}
        var pausing: (Handle) -> Unit = {}
        val slot = ParentRouteSlot<Handle>({ pausing(it) }, { closed.add(it.id); closing(it) })
        fun make(id: Int) = Handle(id).also { made.add(id) }
        fun mount(id: Long, factory: () -> Handle? = { make(id.toInt()) }) =
            slot.mount(id, factory, { shown.add(it.id) }, { fail("unexpected failure for $id") })
        fun releasedExactlyOnce() {
            slot.close(); slot.close()
            assertEquals(made.sorted(), closed.sorted())
            assertEquals(made.size, made.toSet().size)
        }
    }
    @Test fun oldCloseReentryPreemptsOuterFactoryBeforeConstruction() {
        val r = Rig(); r.mount(1)
        r.closing = { if (it.id == 1) r.mount(3) }
        r.mount(2) { fail("superseded factory must not start"); r.make(2) }
        assertEquals(listOf(1, 3), r.shown); assertEquals(listOf(1), r.closed)
        r.slot.close(2); assertEquals(listOf(1), r.closed); r.releasedExactlyOnce()
    }
    @Test fun losingResultDisposalCanReenterWithoutOverwritingNewOwner() {
        val r = Rig(); r.closing = { if (it.id == 1) r.mount(3) }
        r.mount(1) { r.mount(2); r.make(1) }
        assertEquals(listOf(2, 3), r.shown); assertEquals(listOf(1, 2), r.closed)
        r.slot.close(1); assertEquals(listOf(1, 2), r.closed); r.releasedExactlyOnce()
    }
    @Test fun losingFactoryExceptionDoesNotReportFailureForReplacement() {
        val r = Rig()
        r.mount(1) { r.mount(2); throw IllegalStateException() }
        assertEquals(listOf(2), r.shown); assertTrue(r.closed.isEmpty()); r.releasedExactlyOnce()
    }
    @Test fun closeWhileConstructingDisposesReturnedHandleWithoutPresentation() {
        val r = Rig()
        r.mount(1) { r.slot.close(1); r.make(1) }
        assertTrue(r.shown.isEmpty()); assertEquals(listOf(1), r.closed); r.releasedExactlyOnce()
    }
    @Test fun sameTicketAfterCancellationHasDistinctCreationIdentity() {
        val r = Rig()
        r.mount(1) { r.slot.close(1); r.mount(1) { r.make(2) }; r.make(1) }
        assertEquals(listOf(2), r.shown); assertEquals(listOf(1), r.closed); r.releasedExactlyOnce()
    }
    @Test fun sameTicketFactoryRecursionDoesNotFailUnfinishedConstruction() {
        val r = Rig()
        r.mount(1) { r.mount(1) { fail("recursive factory"); r.make(2) }; r.make(1) }
        assertEquals(listOf(1), r.shown); r.releasedExactlyOnce()
    }
    @Test fun retiredPresenterExceptionCannotFailReplacement() {
        val r = Rig()
        r.slot.mount(1, { r.make(1) }, { r.mount(2); throw IllegalStateException() }, { fail("retired failure") })
        assertEquals(listOf(2), r.shown); assertEquals(listOf(1), r.closed); r.releasedExactlyOnce()
    }
    @Test fun currentFactoryExceptionCallsRecoveryWhichCanInstallReplacement() {
        val r = Rig(); var failures = 0
        r.slot.mount(1, { throw IllegalStateException() }, { fail() }, {
            failures++; r.slot.close(1); r.mount(2)
        })
        assertEquals(1, failures); assertEquals(listOf(2), r.shown); r.releasedExactlyOnce()
    }
    @Test fun closeCallbackReentrySurvivesCleanupException() {
        val r = Rig(); r.mount(1)
        r.closing = { if (it.id == 1) { r.mount(2); throw IllegalStateException() } }
        r.slot.close(); assertEquals(listOf(1, 2), r.shown)
        r.slot.close(1); assertEquals(listOf(1), r.closed); r.releasedExactlyOnce()
    }
    @Test fun pauseCallbackReentryPreservesLaterHandle() {
        val r = Rig(); r.mount(1)
        r.pausing = { r.mount(2); throw IllegalStateException() }
        r.slot.pause(); assertEquals(listOf(1, 2), r.shown)
        assertEquals(listOf(1), r.closed); r.releasedExactlyOnce()
    }
    @Test fun emptyFactoryRecoveryCanReenterWithoutLaterStateOverwrite() {
        val r = Rig(); var failures = 0
        r.slot.mount(1, { null }, { fail() }, { failures++; r.mount(2) })
        assertEquals(1, failures); assertEquals(listOf(2), r.shown); r.releasedExactlyOnce()
    }
    @Test fun losingResultDisposalExceptionKeepsReplacement() {
        val r = Rig()
        r.closing = { if (it.id == 1) { r.mount(3); throw IllegalStateException() } }
        r.mount(1) { r.mount(2); r.make(1) }
        assertEquals(listOf(2, 3), r.shown); r.releasedExactlyOnce()
    }
    @Test fun nestedDisposalReentryNeverConstructsSupersededThirdHandle() {
        val r = Rig()
        r.closing = {
            if (it.id == 1) r.mount(3) { fail("superseded third factory"); r.make(3) }
            if (it.id == 2) r.mount(4)
        }
        r.mount(1) { r.mount(2); r.make(1) }
        assertEquals(listOf(2, 4), r.shown); assertEquals(listOf(1, 2), r.closed)
        r.slot.close(1); r.slot.close(2); r.slot.close(3); r.releasedExactlyOnce()
    }
    @Test fun currentPresentationFailureDisposesExactlyOnceBeforeRecovery() {
        val r = Rig(); var failures = 0
        r.slot.mount(1, { r.make(1) }, { throw IllegalStateException() }, {
            failures++; r.slot.close(1); r.mount(2)
        })
        assertEquals(1, failures); assertEquals(listOf(1), r.closed)
        assertEquals(listOf(2), r.shown); r.releasedExactlyOnce()
    }
    @Test fun oldCloseCanCancelPendingReplacementWithoutStartingItsFactory() {
        val r = Rig(); r.mount(1)
        r.closing = { if (it.id == 1) r.slot.close() }
        r.mount(2) { fail("cancelled factory must not start"); r.make(2) }
        assertEquals(listOf(1), r.shown); assertEquals(listOf(1), r.closed); r.releasedExactlyOnce()
    }
    @Test fun losingResultCleanupCanCancelNewOwnerWithoutDoubleRelease() {
        val r = Rig(); r.closing = { if (it.id == 1) r.slot.close() }
        r.mount(1) { r.mount(2); r.make(1) }
        assertEquals(listOf(2), r.shown); assertEquals(listOf(1, 2), r.closed); r.releasedExactlyOnce()
    }

}
