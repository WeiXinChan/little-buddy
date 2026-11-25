package com.littlebuddy.v2

import org.junit.Assert.*
import org.junit.Test

class ManagementStateTest {
    private class Rig {
        var now=100L
        val state=ManagementState { now }
        val scope=ManagementScope("a".repeat(32),2,3,4)
        fun request(): ManagementRequest { state.begin(3,4); return state.scoped(scope)!! }
        fun pause(): ManagementScope { val q=request(); assertTrue(state.paused(q.scope,"b".repeat(32))); return q.scope }
    }
    @Test fun controlCycleAdvancesEpochAndRevisionOnlyAndConsumesReceipt() {
        val r=Rig(); val paused=r.pause(); assertEquals(4,paused.epoch); assertEquals(5,paused.revision)
        val q=r.state.resume()!!; assertEquals("b".repeat(32),q.receipt); assertEquals(paused.turn,q.scope.turn)
        assertEquals(paused.session,q.scope.session); assertEquals(5,q.scope.epoch); assertEquals(6,q.scope.revision)
        assertNull(r.state.resume()); assertTrue(r.state.waiting(q.scope)); assertFalse(r.state.waiting(q.scope))
        assertFalse(r.state.mediaAllowed); assertTrue(r.state.wake()); assertTrue(r.state.mediaAllowed)
    }
    @Test fun pausedStateCannotBootstrapScope() {
        val r=Rig(); assertFalse(r.state.paused(r.scope,"b".repeat(32))); assertNull(r.state.resume())
    }
    @Test fun waitingWithoutResumeIsRejected() {
        val r=Rig(); r.pause(); assertFalse(r.state.waiting(r.scope)); assertFalse(r.state.mediaAllowed)
    }
    @Test fun everyPauseScopeCoordinateMustMatch() {
        for (f in listOf<(ManagementScope)->ManagementScope>({it.copy(session="c".repeat(32))},{it.copy(turn=3)},
            {it.copy(epoch=8)},{it.copy(revision=8)})) {
            val r=Rig(); val q=r.request(); assertFalse(r.state.paused(f(q.scope),"b".repeat(32)))
            assertNull(r.state.resume()); assertFalse(r.state.mediaAllowed)
        }
    }
    @Test fun malformedAndDuplicatePauseReceiptNeverGrantsResumeTwice() {
        val r=Rig(); val q=r.request(); assertFalse(r.state.paused(q.scope,"not-receipt"))
        assertTrue(r.state.paused(q.scope,"b".repeat(32))); assertFalse(r.state.paused(q.scope,"c".repeat(32)))
        assertEquals("b".repeat(32),r.state.resume()!!.receipt); assertNull(r.state.resume())
    }
    @Test fun noMediaOrWakeDuringScopePauseAndResume() {
        val r=Rig(); r.state.begin(3,4); assertFalse(r.state.mediaAllowed); assertFalse(r.state.wake())
        val q=r.state.scoped(r.scope)!!; assertFalse(r.state.wake()); r.state.paused(q.scope,"b".repeat(32))
        assertFalse(r.state.wake()); r.state.resume(); assertFalse(r.state.wake()); assertFalse(r.state.mediaAllowed)
    }
    @Test fun finalWaitingScopeCannotBorrowAnotherSessionOrRevision() {
        val r=Rig(); r.pause(); val q=r.state.resume()!!
        assertFalse(r.state.waiting(q.scope.copy(session="c".repeat(32))))
        assertFalse(r.state.waiting(q.scope.copy(revision=99))); assertFalse(r.state.mediaAllowed)
    }
    @Test fun homeDisconnectAndRevokeDestroyAllLateCapabilities() {
        val r=Rig(); r.pause(); val q=r.state.resume()!!; r.state.close()
        assertFalse(r.state.waiting(q.scope)); assertNull(r.state.resume()); assertFalse(r.state.wake())
        assertFalse(r.state.mediaAllowed); assertFalse(r.state.paused(q.scope,"b".repeat(32)))
    }
    @Test fun controlDeadlineEqualityRejectsLateConfirmation() {
        val r=Rig(); val q=r.request(); r.now=4100
        assertFalse(r.state.paused(q.scope,"b".repeat(32)))
        assertThrows(IllegalStateException::class.java) { r.state.checkDeadline() }
    }
    @Test fun oldScopeCannotBindAfterCurrentConnectionHasEstablishedOne() {
        val r=Rig(); r.pause(); val q=r.state.resume()!!; r.state.waiting(q.scope)
        r.state.begin(q.scope.epoch,q.scope.revision)
        assertNull(r.state.scoped(q.scope.copy(session="c".repeat(32))))
        assertNull(r.state.scoped(q.scope.copy(revision=q.scope.revision-1)))
    }
    @Test fun inputDecisionAndDeadlineDoNotReviveAfterManagement() {
        var now=100L; var seals=0
        val gate=InputGate(Waits(),{now},{},{},{seals++},{},{},{})
        gate.wake(); gate.speech(); gate.quiet(); gate.managementWaiting(3)
        now=20_000; gate.decision(1,Completion.COMPLETE); gate.tick(false)
        assertEquals(0,seals); assertFalse(gate.awake); assertEquals(3,gate.revision)
    }
    @Test fun resumingDoesNotRenewOrLoosenOriginalPlaybackBudget() {
        var now=100L; val budget=PlaybackBudget({now},600); budget.begin()
        now=60_100; budget.tighten(60); assertTrue(budget.expired())
        budget.tighten(600); budget.begin(); assertTrue(budget.expired())
    }
    @Test fun newParticipantRequiresNormalScopeAndCannotBorrowOldPause() {
        val r=Rig(); val old=r.pause(); val q=r.state.resume()!!; r.state.waiting(q.scope); r.state.wake()
        val next=q.scope.copy(session="c".repeat(32),turn=0)
        r.state.normal(next); r.state.begin(next.epoch,next.revision)
        val pending=r.state.scoped(next)!!
        assertFalse(r.state.paused(old,"b".repeat(32)))
        assertTrue(r.state.paused(pending.scope,"d".repeat(32)))
        r.state.normal(old) // Cannot mutate a paused receipt's scope.
        assertEquals(next.session,r.state.resume()!!.scope.session)
    }
}
