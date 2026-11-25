package com.littlebuddy.v2.parent

import org.junit.Assert.*
import org.junit.Test

/** Test-only issuer and memory store; not an Android authentication claim. */
class ManagementRevocationTest {
    private class Rig {
        var now=100L; var revoked=0; var exits=0
        val store=object : ParentStore {
            var value: ParentRecord?=null
            override fun read()=value
            override fun write(record: ParentRecord, authorized: ()->Boolean) { check(authorized()); value=record }
        }
        val domain=ParentDomain(store,{now},{},object: OwnerProof { override fun consume(challenge: OwnerChallenge)=true },"fixture")
        val model=ParentPanelModel({domain},{it()},{it()},{},{exits++},securityRevoked={revoked++})
        init { val page=domain.enterPage(); check(domain.replacePin("012345".toCharArray(),
            domain.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN,page)!!,page)) }
        fun unlock() { model.open(); model.verify("012345".toCharArray()); assertEquals(PanelMode.SETTINGS,model.state.mode) }
    }
    @Test fun currentCancelNeedsNoPinAndDoesNotMasqueradeAsSecurityRevocation() {
        val r=Rig(); r.model.open(); val ticket=r.model.viewToken
        assertTrue(r.model.userAction(ticket) { r.model.exit() }); assertEquals(1,r.exits); assertEquals(0,r.revoked)
        assertFalse(r.model.userAction(ticket) { r.model.exit() }); assertEquals(1,r.exits)
    }
    @Test fun grantExpiryBeforeExitRevokesRetainedTransport() {
        val r=Rig(); r.unlock(); r.now+=ParentDomain.IDLE_MS; r.model.exit()
        assertEquals(1,r.exits); assertEquals(1,r.revoked)
    }
    @Test fun involuntaryTickLockRevokesTransportButNormalVerifiedExitDoesNot() {
        val normal=Rig(); normal.unlock(); normal.model.exit(); assertEquals(0,normal.revoked)
        val expired=Rig(); expired.unlock(); expired.now+=ParentDomain.IDLE_MS; expired.model.tick()
        assertTrue(expired.revoked>0); assertEquals(PanelMode.VERIFY,expired.model.state.mode)
    }
}
