package com.littlebuddy.v2

import org.junit.Assert.*
import org.junit.Test

class ReleaseCompatibilityTest {
    private fun accepts(contract: String?=ReleaseCompatibility.CONTRACT, wire: Int=2, management: Int=1,
        session: String="a".repeat(32), turn: Long=0, epoch: Long=0, revision: Long=0, state: String="active") =
        ReleaseCompatibility.accepts(wire,contract,management,session,turn,epoch,revision,state)
    @Test fun exactKnownNormalScopeIsAccepted() { assertTrue(accepts()); assertTrue(accepts(state="waiting_wake")) }
    @Test fun missingAndUnknownContractAreRejected() { assertFalse(accepts(null)); assertFalse(accepts("future")) }
    @Test fun wrongWireOrManagementVersionAreRejected() { assertFalse(accepts(wire=1)); assertFalse(accepts(management=2)) }
    @Test fun failurePausedExpiredAndUnknownStateCannotAuthorizeCapture() {
        for (state in listOf("failure","paused","expired","unknown")) assertFalse(accepts(state=state))
    }
    @Test fun missingMalformedOrNegativeScopeCannotAuthorizeCapture() {
        assertFalse(accepts(session="")); assertFalse(accepts(session="../../private"))
        assertFalse(accepts(turn=-1)); assertFalse(accepts(epoch=-1)); assertFalse(accepts(revision=-1))
    }
}
