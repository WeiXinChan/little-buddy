package com.littlebuddy.v2.parent

import org.junit.Assert.*
import org.junit.Test

/** Real ParentDomain/Grant/KDF, synthetic storage/owner only in JVM test sources. */
class ParentIntegrationTest {
    private class Store : ParentStore {
        var record: ByteArray? = null
        var before: () -> Unit = {}
        override fun read() = record?.let(ParentCodec::decode)
        override fun write(record: ParentRecord, authorized: () -> Boolean) {
            val bytes = ParentCodec.encode(record); before(); check(authorized()); this.record = bytes
        }
    }
    private val store = Store()
    private var time = 100L
    private var clockReads = 0
    private var afterClock: () -> Unit = {}
    private val d = ParentDomain(store, { val sampled = time; clockReads++; afterClock(); sampled }, {}, object : OwnerProof {
        override fun consume(challenge: OwnerChallenge) = true
    }, "integration-fixture")
    private fun owned(): ParentDomain.Grant {
        val page = d.enterPage(); val proof = d.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN, page)!!
        assertTrue(d.replacePin("012345".toCharArray(), proof, page))
        return d.verify("012345".toCharArray(), d.enterPage())!!
    }
    @Test fun realGrantControlsInMemoryAdmission() {
        val g = owned(); var decisions = 0
        assertFalse(d.acceptProtected(ParentDomain.Grant(g.generation, g.pageEpoch)) { decisions++ })
        assertTrue(d.acceptProtected(g) { decisions++ }); assertEquals(1, decisions)
        d.revoke(); assertFalse(d.acceptProtected(g) { decisions++ }); assertEquals(1, decisions)
    }
    @Test fun admissionAtExactIdleDeadlineRejectsWithoutDecision() {
        val g = owned(); time += ParentDomain.IDLE_MS; var called = false
        assertFalse(d.acceptProtected(g) { called = true }); assertFalse(called)
    }
    @Test fun backgroundAdmissionDoesNotRefreshIdle() {
        val g = owned(); time += 119_999
        assertTrue(d.acceptProtected(g) {})
        time++; assertFalse(d.isAuthorized(g))
    }
    @Test fun routeTransferRevokesOldGrantWithoutRequiringPin() {
        val old = owned(); val next = d.nextPage(old)!!
        assertFalse(d.isAuthorized(old)); assertTrue(d.isAuthorized(next))
        d.revokePage(old); assertTrue(d.isAuthorized(next))
        var accepted = false; assertTrue(d.acceptProtected(next) { accepted = true }); assertTrue(accepted)
    }
    @Test fun routeTransferDoesNotRefreshDeadline() {
        val old = owned(); time += 119_999
        val next = d.nextPage(old)!!; time++
        assertFalse(d.isAuthorized(next)); assertNull(d.nextPage(next))
    }
    @Test fun latePageTransferDoesNotReviveAfterLifecycleRevocation() {
        val old = owned(); d.revoke(); assertNull(d.nextPage(old))
    }
    @Test fun changePinPreservesConfigurationAndRevokesAllPreviousAuthority() {
        val old = owned(); assertTrue(d.saveVolumeLimit(old, 70))
        val pin = "123456".toCharArray(); assertTrue(d.changePin(old, pin)); assertTrue(pin.all { it == '\u0000' })
        assertFalse(d.isAuthorized(old)); assertFalse(d.acceptProtected(old) { fail() })
        val page = d.enterPage(); assertNull(d.verify("012345".toCharArray(), page))
        assertEquals(70, d.volumeLimit(d.verify("123456".toCharArray(), page)!!))
    }
    @Test fun changePinFinalWriteRechecksRevokeAndDoesNotReplaceOldPin() {
        val old = owned(); val before = store.record!!.copyOf(); store.before = { d.revoke() }
        assertFalse(d.changePin(old, "123456".toCharArray())); assertArrayEquals(before, store.record)
        store.before = {}; assertNotNull(d.verify("012345".toCharArray(), d.enterPage()))
    }
    @Test fun unauthorizedPinChangeWipesInputAndDoesNotWrite() {
        val old = owned(); d.revoke(); val before = store.record!!.copyOf(); val pin = "123456".toCharArray()
        assertFalse(d.changePin(old, pin)); assertTrue(pin.all { it == '\u0000' }); assertArrayEquals(before, store.record)
    }
    @Test fun decisionExceptionRevokesScopedAuthorityAndPropagates() {
        val g = owned()
        try { d.acceptProtected(g) { error("synthetic decision fault") }; fail() } catch (_: IllegalStateException) {}
        assertFalse(d.isAuthorized(g))
    }
    @Test fun admissionUsesPostCasDeadlineWitness() {
        val g = owned(); time = 120099; clockReads = 0
        afterClock = { if (clockReads == 2) time = 120100 }
        var called = false
        assertFalse(d.acceptProtected(g) { called = true }); assertFalse(called)
        assertEquals(60, store.read()!!.volumeLimit)
    }
    @Test fun navigationExpiryBetweenSampleAndAdvanceDoesNotReturnGrant() {
        val g = owned(); time = 120099; clockReads = 0
        afterClock = { if (clockReads == 2) time = 120100 }
        assertNull(d.nextPage(g)); assertFalse(d.isAuthorized(g))
    }
    @Test fun normalPinChangeUsesFinalDeadlineWitness() {
        val g = owned(); val before = store.record!!.copyOf()
        store.before = {
            time = 120099; clockReads = 0
            afterClock = { if (clockReads == 2) time = 120100 }
        }
        val pin = "123456".toCharArray()
        assertFalse(d.changePin(g, pin)); assertTrue(pin.all { it == '\u0000' })
        assertArrayEquals(before, store.record)
    }
}
