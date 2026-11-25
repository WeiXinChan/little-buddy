package com.littlebuddy.v2.parent

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import javax.crypto.SecretKey
import javax.crypto.spec.SecretKeySpec

/** Exercises the actual sealed production store with a staged file port, not just the legacy
 * in-memory store bridge. Synthetic file/key ports do not prove Android rename or fsync. */
class PreparedPublicationTest {
    private class Keys : ParentKeyProvider {
        var key: SecretKey? = null
        var creations = 0
        override fun exists() = key != null
        override fun existing() = key
        override fun create(): SecretKey {
            check(key == null); creations++
            return SecretKeySpec(ByteArray(32) { 17 }, "AES").also { key = it }
        }
    }
    private class File : ParentRecordFile {
        var bytes: ByteArray? = null
        var beforeClaim: () -> Unit = {}
        var afterClaim: () -> Unit = {}
        override fun read() = bytes?.copyOf()
        override fun commit(bytes: ByteArray, authorized: () -> Boolean) = error("production publish must use explicit protocol")
        override fun publish(bytes: ByteArray, transaction: ParentCommit) {
            beforeClaim() // Prepared IO is complete only when this returns.
            transaction.claim()
            afterClaim() // Decided; a delayed physical publish cannot delay HOME.
            this.bytes = bytes.copyOf()
        }
    }
    private val keys = Keys()
    private val file = File()
    private val sealed = SealedParentStore(file, keys, "test-binding".toByteArray())
    private val d = ParentDomain(sealed, { 100L }, {}, object : OwnerProof {
        override fun consume(challenge: OwnerChallenge) = true
    }, "test-binding")
    private fun init() {
        val page = d.enterPage(); val proof = d.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN, page)!!
        assertTrue(d.replacePin("012345".toCharArray(), proof, page))
    }
    private fun blockedWrite(afterDecision: Boolean, action: () -> Boolean): Boolean {
        val entered = CountDownLatch(1); val release = CountDownLatch(1); val revoked = CountDownLatch(1)
        val result = AtomicReference<Boolean>(); val error = AtomicReference<Throwable>()
        val block = { entered.countDown(); check(release.await(5, TimeUnit.SECONDS)) }
        if (afterDecision) file.afterClaim = block else file.beforeClaim = block
        val worker = Thread { try { result.set(action()) } catch (t: Throwable) { error.set(t) } }
        val lifecycle = Thread { d.revoke(); revoked.countDown() }
        try {
            worker.start(); assertTrue(entered.await(3, TimeUnit.SECONDS))
            lifecycle.start(); assertTrue(revoked.await(300, TimeUnit.MILLISECONDS))
        } finally {
            release.countDown(); worker.join(4000)
            if (lifecycle.state != Thread.State.NEW) lifecycle.join(1000)
        }
        assertFalse(worker.isAlive); assertFalse(lifecycle.isAlive); assertNull(error.get())
        return result.get()!!
    }
    @Test fun revokeBeforeFinalClaimAbortsSealedProductionWrite() {
        init(); val g = d.verify("012345".toCharArray(), d.enterPage())!!; val before = file.bytes!!.copyOf()
        assertFalse(blockedWrite(false) { d.saveVolumeLimit(g, 80) })
        assertArrayEquals(before, file.bytes); assertEquals(60, sealed.read()!!.volumeLimit)
        assertEquals(1, keys.creations); assertEquals(ParentDomain.State.LOCKED, d.state())
    }
    @Test fun revokeAfterFinalClaimDoesNotUndoDecidedTransactionOrRestoreGrant() {
        init(); val g = d.verify("012345".toCharArray(), d.enterPage())!!
        assertTrue(blockedWrite(true) { d.saveVolumeLimit(g, 80) })
        assertEquals(80, sealed.read()!!.volumeLimit)
        assertFalse(d.saveVolumeLimit(g, 90)); assertEquals(ParentDomain.State.LOCKED, d.state())
    }
    @Test fun freshAliasCreatedButCancelledBeforeClaimMustQuarantine() {
        val page = d.enterPage(); val proof = d.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN, page)!!
        assertFalse(blockedWrite(false) { d.replacePin("012345".toCharArray(), proof, page) })
        assertEquals(1, keys.creations); assertNull(file.bytes)
        assertEquals(ParentDomain.State.QUARANTINED, d.state())
        try { sealed.read(); fail("interrupted initialization reopened") } catch (_: IllegalStateException) {}
    }
}
