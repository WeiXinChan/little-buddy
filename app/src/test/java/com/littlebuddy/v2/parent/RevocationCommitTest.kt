package com.littlebuddy.v2.parent

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

class RevocationCommitTest {
    private class Store : ParentStore {
        var bytes: ByteArray? = null
        var before: (ParentRecord) -> Unit = {}
        var after: (ParentRecord) -> Unit = {}
        var writes = 0
        override fun read() = bytes?.let(ParentCodec::decode)
        override fun write(record: ParentRecord, authorized: () -> Boolean) {
            val prepared = ParentCodec.encode(record)
            before(record)
            check(authorized())
            bytes = prepared; writes++
            after(record)
        }
    }
    private class Barrier {
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        fun block() { entered.countDown(); check(release.await(5, TimeUnit.SECONDS)) }
    }
    private class Result<T>(action: () -> T) {
        val value = AtomicReference<T>()
        val error = AtomicReference<Throwable>()
        val thread = Thread { try { value.set(action()) } catch (t: Throwable) { error.set(t) } }
        init { thread.start() }
        fun join() {
            thread.join(4000); assertFalse("worker leaked", thread.isAlive); assertNull(error.get())
        }
    }
    private val store = Store()
    private var time = 100L
    private val issuer = object : OwnerProof { override fun consume(challenge: OwnerChallenge) = true }
    private fun domain(owner: OwnerProof = issuer, hasher: PinHasher = PinHasher()) =
        ParentDomain(store, { time }, {}, owner, "test-binding", hasher)
    private fun initialize(d: ParentDomain) {
        val page = d.enterPage()
        val proof = d.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN, page)!!
        assertTrue(d.replacePin("012345".toCharArray(), proof, page))
    }
    private fun grant(d: ParentDomain): ParentDomain.Grant = d.verify("012345".toCharArray(), d.enterPage())!!
    private fun timely(action: () -> Unit) {
        val done = CountDownLatch(1)
        val thread = Thread { try { action() } finally { done.countDown() } }
        thread.start()
        assertTrue("lifecycle invalidation waited for IO", done.await(300, TimeUnit.MILLISECONDS))
        thread.join(1000); assertFalse(thread.isAlive)
    }

    @Test fun committedValueSurvivesRevokeWhilePostcommitIoIsBlocked() {
        val d = domain(); initialize(d); val g = grant(d); val barrier = Barrier()
        store.after = { barrier.block() }
        val writer = Result { d.saveVolumeLimit(g, 80) }
        try {
            assertTrue(barrier.entered.await(3, TimeUnit.SECONDS))
            assertEquals(80, store.read()!!.volumeLimit)
            assertNull(d.volumeLimit(g)) // No stale memory view while readback is pending.
            timely { d.revoke() }
        } finally { barrier.release.countDown(); writer.join() }
        assertEquals(true, writer.value.get()); assertEquals(80, store.read()!!.volumeLimit)
        assertFalse(d.saveVolumeLimit(g, 90)); assertEquals(ParentDomain.State.LOCKED, d.state())
    }
    @Test fun pageChangeBeforeCommitRejectsOldWriteAndDoesNotQueueConcurrentMutation() {
        val d = domain(); initialize(d); val g = grant(d); val barrier = Barrier()
        store.before = { barrier.block() }
        val writer = Result { d.saveVolumeLimit(g, 80) }
        try {
            assertTrue(barrier.entered.await(3, TimeUnit.SECONDS))
            assertFalse(d.saveVolumeLimit(g, 90))
            timely { d.enterPage() }
        } finally { barrier.release.countDown(); writer.join() }
        assertEquals(false, writer.value.get()); assertEquals(60, store.read()!!.volumeLimit)
        assertEquals(ParentDomain.State.LOCKED, d.state())
    }
    @Test fun initializationLateCommitIsRejected() {
        val d = domain(); val page = d.enterPage()
        val proof = d.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN, page)!!
        val barrier = Barrier(); store.before = { barrier.block() }
        val writer = Result { d.replacePin("012345".toCharArray(), proof, page) }
        try {
            assertTrue(barrier.entered.await(3, TimeUnit.SECONDS)); timely { d.revoke() }
        } finally { barrier.release.countDown(); writer.join() }
        assertEquals(false, writer.value.get()); assertNull(store.bytes)
    }
    @Test fun recoveryLateCommitKeepsOldPinAndSettings() {
        val d = domain(); initialize(d); val g = grant(d); assertTrue(d.saveVolumeLimit(g, 70))
        val page = d.enterPage(); val proof = d.beginOwnerOperation(OwnerOperation.RESET_PIN, page)!!
        val barrier = Barrier(); store.before = { barrier.block() }
        val writer = Result { d.replacePin("123456".toCharArray(), proof, page) }
        try {
            assertTrue(barrier.entered.await(3, TimeUnit.SECONDS)); timely { d.revoke() }
        } finally { barrier.release.countDown(); writer.join() }
        store.before = {}
        assertEquals(false, writer.value.get()); assertEquals(70, d.volumeLimit(grant(d)))
    }
    @Test fun expiredRecoveryCannotCommitPreparedPin() {
        val d = domain(); initialize(d); val page = d.enterPage()
        val proof = d.beginOwnerOperation(OwnerOperation.RESET_PIN, page)!!
        val before = store.bytes!!.copyOf(); val barrier = Barrier(); store.before = { barrier.block() }
        val writer = Result { d.replacePin("123456".toCharArray(), proof, page) }
        try { assertTrue(barrier.entered.await(3, TimeUnit.SECONDS)); time += 60_000 }
        finally { barrier.release.countDown(); writer.join() }
        assertEquals(false, writer.value.get()); assertArrayEquals(before, store.bytes)
    }
    @Test fun successfulVerifyAfterRevokeCannotPublishGrantOrClearReservation() {
        val d = domain(); initialize(d); val page = d.enterPage(); val barrier = Barrier()
        store.before = { if (it.failures == 0) barrier.block() }
        val verifier = Result { d.verify("012345".toCharArray(), page) }
        try { assertTrue(barrier.entered.await(3, TimeUnit.SECONDS)); timely { d.revoke() } }
        finally { barrier.release.countDown(); verifier.join() }
        assertNull(verifier.value.get()); assertEquals(1, store.read()!!.failures)
        assertEquals(ParentDomain.State.LOCKED, d.state())
    }
    @Test fun revokedBeforeReservationDoesNotHashOrWriteFailureCount() {
        var hashes = 0
        val hasher = object : PinHasher() {
            override fun derive(pin: CharArray, salt: ByteArray): ByteArray {
                hashes++; return super.derive(pin, salt)
            }
        }
        val d = domain(hasher = hasher); initialize(d); hashes = 0
        val page = d.enterPage(); val writes = store.writes; val barrier = Barrier()
        store.before = { barrier.block() }
        val verifier = Result { d.verify("012345".toCharArray(), page) }
        try { assertTrue(barrier.entered.await(3, TimeUnit.SECONDS)); timely { d.revoke() } }
        finally { barrier.release.countDown(); verifier.join() }
        assertNull(verifier.value.get()); assertEquals(0, hashes)
        assertEquals(writes, store.writes); assertEquals(0, store.read()!!.failures)
    }
    @Test fun revokeDuringKdfAndConcurrentVerifyReplaceRejectWithoutExtraReservation() {
        val barrier = Barrier()
        val hasher = object : PinHasher() {
            var blocking = false
            override fun derive(pin: CharArray, salt: ByteArray): ByteArray {
                if (blocking) barrier.block()
                return super.derive(pin, salt)
            }
        }
        val d = domain(hasher = hasher); initialize(d); val page = d.enterPage()
        val proof = d.beginOwnerOperation(OwnerOperation.RESET_PIN, page)!!; hasher.blocking = true
        val verifier = Result { d.verify("012345".toCharArray(), page) }
        try {
            assertTrue(barrier.entered.await(3, TimeUnit.SECONDS))
            val attempts = store.writes
            assertNull(d.verify("012345".toCharArray(), page))
            assertFalse(d.replacePin("123456".toCharArray(), proof, page))
            assertEquals(attempts, store.writes); timely { d.revoke() }
        } finally { barrier.release.countDown(); verifier.join() }
        assertNull(verifier.value.get()); assertEquals(1, store.read()!!.failures)
    }
    @Test fun revokeDuringOwnerProofDoesNotWaitAndConcurrentWorkersReject() {
        val barrier = Barrier()
        var blocking = false
        val owner = object : OwnerProof {
            override fun consume(challenge: OwnerChallenge): Boolean { if (blocking) barrier.block(); return true }
        }
        val d = domain(owner); initialize(d); val page = d.enterPage()
        val proof = d.beginOwnerOperation(OwnerOperation.RESET_PIN, page)!!; blocking = true
        val writer = Result { d.replacePin("123456".toCharArray(), proof, page) }
        try {
            assertTrue(barrier.entered.await(3, TimeUnit.SECONDS))
            assertNull(d.verify("012345".toCharArray(), page))
            assertFalse(d.replacePin("123456".toCharArray(), proof, page))
            timely { d.revoke() }
        } finally { barrier.release.countDown(); writer.join() }
        assertEquals(false, writer.value.get())
    }
    @Test fun diskFailureAfterDecisionQuarantinesWithoutReportingSuccess() {
        val d = domain(); initialize(d); val g = grant(d)
        store.after = { error("synthetic post-publication disk fault") }
        assertFalse(d.saveVolumeLimit(g, 80))
        assertEquals(80, store.read()!!.volumeLimit) // Indeterminate durable outcome, no silent retry.
        assertEquals(ParentDomain.State.QUARANTINED, d.state()); assertNull(d.volumeLimit(g))
    }
    @Test fun finalClaimAndRevokeUseSameAtomicOrdering() {
        val epochs = ParentEpoch(); val page = epochs.revoke()
        val pending = ParentCommit({ epochs.current() == page }, { epochs.claim(page) })
        pending.checkAllowed(); epochs.revoke()
        try { pending.claim(); fail("stale prepared operation committed") } catch (_: ParentCommitRejected) {}
        val next = epochs.current()
        val committed = ParentCommit({ epochs.current() == next }, { epochs.claim(next) })
        assertTrue(committed.claim()); epochs.revoke(); assertTrue(committed.committed)
        assertFalse(epochs.claim(next))
    }
}
