package com.littlebuddy.v2.parent

import org.junit.Assert.*
import org.junit.Test
import javax.crypto.SecretKey
import javax.crypto.spec.SecretKeySpec

/** Production SealedParentStore + real JVM AES-GCM; only key/file ports are synthetic.
 * These tests do not execute Android Keystore, AtomicFile or device faults. */
class ParentKeyStoreTest {
    private class Keys : ParentKeyProvider {
        var key: SecretKey? = null
        var invalid = false
        var creations = 0
        override fun exists() = key != null
        override fun existing(): SecretKey? {
            check(!invalid) { "synthetic key invalidation" }
            return key
        }
        override fun create(): SecretKey {
            check(key == null)
            creations++
            return syntheticKey(17).also { key = it }
        }
    }
    private class File : ParentRecordFile {
        var bytes: ByteArray? = null
        var commits = 0
        var failCommit = false
        override fun read() = bytes?.copyOf()
        override fun commit(bytes: ByteArray, authorized: () -> Boolean) {
            check(!failCommit) { "synthetic disk fault" }
            check(authorized())
            commits++; this.bytes = bytes.copyOf()
        }
    }
    private val keys = Keys()
    private val file = File()
    private val aad = "v2:parent:synthetic-binding".toByteArray()
    private var workerAllowed = true
    private val issuer = object : OwnerProof {
        override fun consume(challenge: OwnerChallenge) = true
    }
    private fun storage() = SealedParentStore(file, keys, aad)
    private fun domain(store: ParentStore = storage(), proof: OwnerProof = issuer) =
        ParentDomain(store, { 100L }, { check(workerAllowed) }, proof, "synthetic-binding")
    private fun seed() {
        keys.key = syntheticKey(17)
        file.bytes = ParentEnvelope.seal(ParentCodec.encode(ParentRecord(SALT, HASH)), keys.key!!, aad)
    }
    private fun assertNoReplacement(before: ByteArray?) {
        assertEquals(0, keys.creations); assertEquals(0, file.commits)
        assertArrayEquals(before, file.bytes)
    }
    private fun initialize(d: ParentDomain): Boolean {
        val page = d.enterPage()
        val proof = d.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN, page)!!
        return d.replacePin("012345".toCharArray(), proof, page)
    }

    @Test fun existingRecordWithoutKeyQuarantinesAtStartup() {
        seed(); val before = file.bytes!!.copyOf(); keys.key = null
        val d = domain()
        assertEquals(ParentDomain.State.QUARANTINED, d.state())
        assertNull(d.verify("012345".toCharArray(), d.enterPage()))
        assertNoReplacement(before)
    }
    @Test fun keyRemovedAfterOpenRejectsVerifyWithoutCreatingOrOverwriting() {
        seed(); val d = domain(); val before = file.bytes!!.copyOf(); keys.key = null
        assertNull(d.verify("012345".toCharArray(), d.enterPage()))
        assertEquals(ParentDomain.State.QUARANTINED, d.state()); assertNoReplacement(before)
    }
    @Test fun keyRemovedAfterAuthorizationRejectsSaveWithoutCreatingOrOverwriting() {
        seed(); val d = domain(); val grant = d.verify("012345".toCharArray(), d.enterPage())!!
        file.commits = 0; val before = file.bytes!!.copyOf(); keys.key = null
        assertFalse(d.saveVolumeLimit(grant, 80))
        assertEquals(ParentDomain.State.QUARANTINED, d.state()); assertNoReplacement(before)
    }
    @Test fun invalidKeyAfterAuthorizationRejectsSaveWithoutOverwrite() {
        seed(); val d = domain(); val grant = d.verify("012345".toCharArray(), d.enterPage())!!
        file.commits = 0; val before = file.bytes!!.copyOf(); keys.invalid = true
        assertFalse(d.saveVolumeLimit(grant, 80))
        assertEquals(ParentDomain.State.QUARANTINED, d.state()); assertNoReplacement(before)
    }
    @Test fun replacedKeyCannotOverwritePreviouslyOpenedDomain() {
        seed(); val d = domain(); val before = file.bytes!!.copyOf(); keys.key = syntheticKey(18)
        assertNull(d.verify("012345".toCharArray(), d.enterPage()))
        assertEquals(ParentDomain.State.QUARANTINED, d.state()); assertNoReplacement(before)
    }
    @Test fun freshTrustedInitializationCreatesExactlyOnce() {
        val d = domain(); assertTrue(initialize(d))
        assertEquals(1, keys.creations)
        val grant = d.verify("012345".toCharArray(), d.enterPage())!!
        assertTrue(d.saveVolumeLimit(grant, 80))
        assertEquals(1, keys.creations)
        val restarted = domain()
        assertEquals(80, restarted.volumeLimit(restarted.verify("012345".toCharArray(), restarted.enterPage())!!))
        assertEquals(1, keys.creations)
    }
    @Test fun missingOwnerProviderNeverCreatesKey() {
        val d = domain(proof = UnconfiguredOwnerProof)
        assertFalse(initialize(d)); assertNoReplacement(null)
    }
    @Test fun firstCommitFailureAfterCreationQuarantinesAndCannotRetry() {
        val store = storage(); val d = domain(store); file.failCommit = true
        assertFalse(initialize(d)); assertEquals(1, keys.creations)
        assertEquals(ParentDomain.State.QUARANTINED, d.state()); assertNull(file.bytes)
        assertEquals(0, file.commits)
        file.failCommit = false
        try { store.write(ParentRecord(SALT, HASH)) { true }; fail("retry accepted") }
        catch (_: IllegalStateException) {}
        assertEquals(1, keys.creations); assertEquals(0, file.commits)
        assertEquals(ParentDomain.State.QUARANTINED, domain().state())
    }
    @Test fun rejectedAuthorizationNeverConsumesFreshKeyCreation() {
        val store = storage(); assertNull(store.read())
        try { store.write(ParentRecord(SALT, HASH)) { false }; fail("unauthorized creation") }
        catch (_: IllegalStateException) {}
        assertNoReplacement(null)
    }
    @Test fun verifyWorkerFailureStillErasesPin() {
        seed(); val d = domain(); val page = d.enterPage(); val before = file.bytes!!.copyOf()
        val pin = "012345".toCharArray(); workerAllowed = false
        try { d.verify(pin, page); fail("worker guard bypass") } catch (_: IllegalStateException) {}
        assertTrue(pin.all { it == '\u0000' }); assertNoReplacement(before)
    }
    @Test fun replacePinWorkerFailureStillErasesPin() {
        val d = domain(); val page = d.enterPage()
        val proof = d.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN, page)!!
        val pin = "012345".toCharArray(); workerAllowed = false
        try { d.replacePin(pin, proof, page); fail("worker guard bypass") } catch (_: IllegalStateException) {}
        assertTrue(pin.all { it == '\u0000' }); assertNoReplacement(null)
    }
    companion object {
        private val SALT = ByteArray(16) { 1 }
        private val HASH = PinHasher().derive("012345".toCharArray(), SALT)
        private fun syntheticKey(value: Int) = SecretKeySpec(ByteArray(32) { value.toByte() }, "AES")
    }
}
