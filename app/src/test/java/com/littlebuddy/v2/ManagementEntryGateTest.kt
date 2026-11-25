package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test

class ManagementEntryGateTest {
    private val scope=ManagementScope("a".repeat(32),0,0,1)
    @Test fun eventCannotBootstrapAndCurrentTokenIsConsumedOnce() {
        val gate=ManagementEntryGate { 100L };assertNull(gate.issue(scope,1000));gate.bind(scope)
        val entry=gate.issue(scope,1000)!!;var calls=0
        assertTrue(gate.accept(entry,0,1){calls++;true});assertFalse(gate.accept(entry,0,1){calls++;true})
        gate.bind(scope);assertNull(gate.issue(scope,1000));assertEquals(1,calls)
    }
    @Test fun newRevisionAndNormalScopeDoNotLendOldTokenAuthority() {
        val gate=ManagementEntryGate { 100L };gate.bind(scope);val old=gate.issue(scope,1000)!!
        val next=scope.copy(revision=2);gate.bind(next);val fresh=gate.issue(next,1000)!!
        assertFalse(gate.accept(old,0,2){error("borrowed new scope")})
        assertTrue(gate.accept(fresh,0,2){true})
    }
    @Test fun homeCloseOrNewInputClearRefusesEvenIdenticalWireScopeReplay() {
        val gate=ManagementEntryGate { 100L };gate.bind(scope);val old=gate.issue(scope,1000)!!;gate.clear();gate.bind(scope)
        assertFalse(gate.accept(old,0,1){error("revived old entry")})
        assertFalse(gate.accept(ManagementEntry(scope,1000),0,1){error("forged entry")})
    }
    @Test fun equalityDeadlineRejectsQueuedIntent() {
        var now=100L;val gate=ManagementEntryGate { now };gate.bind(scope)
        val entry=gate.issue(scope,200)!!;now=200
        assertFalse(gate.accept(entry,0,1){error("expired decision")})
    }
    @Test fun homeAndNewPageWinReservationCasWithoutBorrowingCurrentPage() {
        val requests=ManagementPageRequests();val old=requests.reserve(1);requests.clear()
        assertFalse(requests.claim(old));assertFalse(requests.requested(1))
        val stale=requests.reserve(2);requests.immediate(3)
        assertFalse(requests.claim(stale));assertFalse(requests.requested(2));assertTrue(requests.requested(3))
    }
}
