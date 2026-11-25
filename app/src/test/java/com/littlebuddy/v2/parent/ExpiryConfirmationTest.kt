package com.littlebuddy.v2.parent

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.atomic.AtomicLong
import javax.crypto.SecretKey
import javax.crypto.spec.SecretKeySpec

/** Real sealed store; synthetic monotonic clock, owner proof and key/file ports. */
class ExpiryConfirmationTest {
    private class Clock {
        val time = AtomicLong(100)
        var armed = false
        var reads = 0
        var atRead = 1
        var afterSample: () -> Unit = {}
        fun now(): Long {
            val sampled = time.get()
            if (armed && ++reads == atRead) afterSample()
            return sampled
        }
    }
    private class Keys : ParentKeyProvider {
        var key: SecretKey? = null
        var creates = 0
        override fun existing() = key
        override fun exists() = key != null
        override fun create(): SecretKey {
            check(key == null); creates++
            return SecretKeySpec(ByteArray(32) { 19 }, "AES").also { key = it }
        }
    }
    private class File(val clock: Clock) : ParentRecordFile {
        var bytes: ByteArray? = null
        var armFinal = false
        var beforeClaim: () -> Unit = {}
        var decisions = 0
        override fun read() = bytes?.copyOf()
        override fun commit(bytes: ByteArray, authorized: () -> Boolean) = error("explicit publish required")
        override fun publish(bytes: ByteArray, transaction: ParentCommit) {
            if (armFinal) { clock.armed = true; clock.reads = 0 }
            try {
                beforeClaim()
                transaction.claim()
                assertTrue(transaction.committed)
                decisions++; this.bytes = bytes.copyOf()
            } finally { clock.armed = false }
        }
    }
    private class Rig {
        val clock = Clock()
        val keys = Keys()
        val file = File(clock)
        val store = SealedParentStore(file, keys, "synthetic-expiry-binding".toByteArray())
        val d = ParentDomain(store, clock::now, {}, object : OwnerProof {
            override fun consume(challenge: OwnerChallenge) = true
        }, "synthetic-expiry-binding")
        fun proof(operation: OwnerOperation): Pair<Long, OwnerChallenge> {
            val page = d.enterPage()
            return page to d.beginOwnerOperation(operation, page)!!
        }
        fun initialize() {
            val (page, p) = proof(OwnerOperation.INITIALIZE_PIN)
            assertTrue(d.replacePin("012345".toCharArray(), p, page))
        }
        fun grant(): ParentDomain.Grant = d.verify("012345".toCharArray(), d.enterPage())!!
    }

    @Test fun initializationExpiryAfterFinalSampleBeforeCasQuarantinesCreatedAlias() {
        val r = Rig(); val (page, p) = r.proof(OwnerOperation.INITIALIZE_PIN)
        r.clock.time.set(p.expiresAt - 1); r.file.armFinal = true
        r.clock.afterSample = { r.clock.time.set(p.expiresAt) }
        assertFalse(r.d.replacePin("012345".toCharArray(), p, page))
        assertNull(r.file.bytes); assertEquals(0, r.file.decisions); assertEquals(1, r.keys.creates)
        assertEquals(ParentDomain.State.QUARANTINED, r.d.state())
        assertFalse(r.d.replacePin("012345".toCharArray(), p, page))
        assertEquals(1, r.keys.creates)
    }
    @Test fun recoveryExpiryAfterFinalSampleBeforeCasKeepsOldPinConfigAndCounter() {
        val r = Rig(); r.initialize(); val g = r.grant(); assertTrue(r.d.saveVolumeLimit(g, 70))
        val (page, p) = r.proof(OwnerOperation.RESET_PIN)
        assertNull(r.d.verify("999999".toCharArray(), page))
        // Verification consumed the old challenge; request a fresh recovery proof for this page.
        val proof = r.d.beginOwnerOperation(OwnerOperation.RESET_PIN, page)!!
        val before = r.file.bytes!!.copyOf(); val commits = r.file.decisions
        r.clock.time.set(proof.expiresAt - 1); r.file.armFinal = true
        r.clock.afterSample = { r.clock.time.set(proof.expiresAt) }
        assertFalse(r.d.replacePin("123456".toCharArray(), proof, page))
        assertArrayEquals(before, r.file.bytes); assertEquals(commits, r.file.decisions)
        assertEquals(1, r.store.read()!!.failures); assertEquals(70, r.store.read()!!.volumeLimit)
        assertEquals(ParentDomain.State.LOCKED, r.d.state()); assertEquals(1, r.keys.creates)
        r.file.armFinal = false
        assertEquals(70, r.d.volumeLimit(r.grant()))
        assertFalse(r.d.replacePin("123456".toCharArray(), p, page))
    }
    @Test fun ownerDeadlineEqualityBeforeCasDoesNotPublish() {
        val r = Rig(); r.initialize(); val (page, p) = r.proof(OwnerOperation.RESET_PIN)
        val before = r.file.bytes!!.copyOf()
        r.clock.time.set(p.expiresAt - 1); r.file.beforeClaim = { r.clock.time.set(p.expiresAt) }
        assertFalse(r.d.replacePin("123456".toCharArray(), p, page))
        assertArrayEquals(before, r.file.bytes); assertEquals(ParentDomain.State.LOCKED, r.d.state())
        assertNull(r.d.beginOwnerOperation(OwnerOperation.RESET_PIN, page - 1))
    }
    @Test fun grantDeadlineEqualityBeforeCasDoesNotPublish() {
        val r = Rig(); r.initialize(); val g = r.grant(); val before = r.file.bytes!!.copyOf()
        r.clock.time.set(120099); r.file.beforeClaim = { r.clock.time.set(120100) }
        assertFalse(r.d.saveVolumeLimit(g, 80)); assertArrayEquals(before, r.file.bytes)
        assertEquals(ParentDomain.State.LOCKED, r.d.state())
    }
    @Test fun expiryAfterPostCasSampleKeepsEarlierInTimeDecision() {
        val r = Rig(); r.initialize(); val g = r.grant()
        r.clock.time.set(120099); r.file.armFinal = true; r.clock.atRead = 3
        // valid has two samples; the third is AFTER CAS. Its captured value certifies CAS.
        r.clock.afterSample = { r.clock.time.set(120100) }
        assertTrue(r.d.saveVolumeLimit(g, 80)); assertEquals(80, r.store.read()!!.volumeLimit)
        assertEquals(ParentDomain.State.LOCKED, r.d.state()); assertFalse(r.d.saveVolumeLimit(g, 90))
    }
    @Test fun ownerExpiryAfterPostCasSampleKeepsEarlierInTimeDecision() {
        val r = Rig(); r.initialize(); val (page, p) = r.proof(OwnerOperation.RESET_PIN)
        r.clock.time.set(p.expiresAt - 1); r.file.armFinal = true; r.clock.atRead = 2
        r.clock.afterSample = { r.clock.time.set(p.expiresAt) }
        assertTrue(r.d.replacePin("123456".toCharArray(), p, page))
        r.file.armFinal = false
        val next = r.d.enterPage(); assertNull(r.d.verify("012345".toCharArray(), next))
        assertNotNull(r.d.verify("123456".toCharArray(), next))
    }
    @Test fun confirmationRejectIsTerminalAndNeverSetsCommitted() {
        var decisions = 0; var confirmations = 0
        val tx = ParentCommit({ true }, { decisions++; true }, { confirmations++; false })
        repeat(2) {
            try { tx.claim(); fail("aborted claim retried") } catch (_: ParentCommitRejected) {}
        }
        assertFalse(tx.committed); assertEquals(1, decisions); assertEquals(1, confirmations)
    }
    @Test fun revokeAfterCasBeforeConfirmationDoesNotUndoEarlierDecision() {
        val r = Rig(); r.initialize(); val g = r.grant()
        r.file.armFinal = true; r.clock.atRead = 3
        r.clock.afterSample = { r.d.revoke() }
        assertTrue(r.d.saveVolumeLimit(g, 80)); assertEquals(80, r.store.read()!!.volumeLimit)
        assertFalse(r.d.saveVolumeLimit(g, 90)); assertEquals(ParentDomain.State.LOCKED, r.d.state())
    }
}
