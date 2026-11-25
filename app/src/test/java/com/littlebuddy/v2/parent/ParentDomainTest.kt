package com.littlebuddy.v2.parent

import org.junit.Assert.*
import org.junit.Test

class ParentDomainTest {
    private class Memory : ParentStore {
        var bytes: ByteArray? = null
        var failRead = false
        var failWrite = false
        var beforeCommit: () -> Unit = {}
        var writes = 0
        override fun read(): ParentRecord? {
            check(!failRead)
            return bytes?.let(ParentCodec::decode)
        }
        override fun write(record: ParentRecord, authorized: () -> Boolean) {
            check(!failWrite)
            val prepared = ParentCodec.encode(record)
            beforeCommit(); check(authorized())
            bytes = prepared; writes++
        }
    }
    private var time = 100L
    private val store = Memory()
    private val syntheticIssuer = object : OwnerProof {
        override fun consume(challenge: OwnerChallenge) = true
    }
    private fun domain(proof: OwnerProof = syntheticIssuer) =
        ParentDomain(store, { time }, {}, proof, "synthetic-binding")
    private fun owned(): Pair<ParentDomain, Long> {
        val d = domain(); val page = d.enterPage()
        val challenge = d.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN, page)!!
        assertTrue(d.replacePin("012345".toCharArray(), challenge, page))
        return d to d.enterPage()
    }
    private fun unlock(d: ParentDomain, page: Long) = d.verify("012345".toCharArray(), page)!!

    @Test fun noProviderCannotInitializeOrRecover() {
        val d = domain(UnconfiguredOwnerProof); val page = d.enterPage()
        val c = d.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN, page)!!
        assertFalse(d.replacePin("012345".toCharArray(), c, page))
        assertNull(store.bytes); assertEquals(ParentDomain.State.UNOWNED, d.state())
        assertNull(d.verify("012345".toCharArray(), page))
    }
    @Test fun asciiAndLeadingZerosAndInputErasure() {
        val (d, page) = owned()
        for (invalid in listOf("12345", "1234567", "１２３４５６", " 12345", "abcdef")) {
            val input = invalid.toCharArray(); assertNull(d.verify(input, page))
            assertTrue(input.all { it == '\u0000' })
        }
        val input = "012345".toCharArray()
        assertNotNull(d.verify(input, page)); assertTrue(input.all { it == '\u0000' })
    }
    @Test fun wrongPinAndForgedGrantDeny() {
        val (d, page) = owned()
        assertNull(d.verify("012346".toCharArray(), page))
        assertFalse(d.saveVolumeLimit(ParentDomain.Grant(0, page), 90))
        assertEquals(60, d.volumeLimit(unlock(d, page)))
    }
    @Test fun grantIsBoundToDomainAndPage() {
        val (d, page) = owned(); val g = unlock(d, page)
        assertFalse(domain().saveVolumeLimit(g, 80))
        d.enterPage(); assertFalse(d.saveVolumeLimit(g, 80))
        assertNull(d.verify("012345".toCharArray(), page))
    }
    @Test fun lifecycleRevocationRejectsLateWrite() {
        val (d, page) = owned(); val g = unlock(d, page)
        d.revoke(); assertFalse(d.saveVolumeLimit(g, 80))
        assertEquals(60, store.read()!!.volumeLimit)
    }
    @Test fun exactIdleBoundaryAndOnlyLocalActionRefreshes() {
        val (d, page) = owned(); val g = unlock(d, page)
        time += 119_999; assertTrue(d.localAction(g))
        time += 119_999; assertEquals(ParentDomain.State.AUTHORIZED, d.state())
        time++; assertEquals(ParentDomain.State.LOCKED, d.state())
        assertFalse(d.localAction(g)); assertFalse(d.saveVolumeLimit(g, 80))
    }
    @Test fun readAndStateDoNotExtendIdle() {
        val (d, page) = owned(); val g = unlock(d, page)
        time += 119_999; assertEquals(60, d.volumeLimit(g)); d.state()
        time++; assertNull(d.volumeLimit(g))
    }
    @Test fun settingsPersistButGrantDoesNotSurviveProcess() {
        val (d, page) = owned(); val g = unlock(d, page)
        assertTrue(d.saveVolumeLimit(g, 75))
        val restarted = domain(); assertEquals(ParentDomain.State.LOCKED, restarted.state())
        assertFalse(restarted.saveVolumeLimit(g, 99))
        assertEquals(75, restarted.volumeLimit(unlock(restarted, restarted.enterPage())))
    }
    @Test fun fifthFailureCooldownPersistsAcrossRepeatedRestart() {
        val (d, page) = owned()
        repeat(5) { assertNull(d.verify("999999".toCharArray(), page)) }
        assertEquals(ParentDomain.State.COOLDOWN, d.state())
        assertNull(d.verify("012345".toCharArray(), page))
        time += 59_999
        val restarted = domain(); assertEquals(ParentDomain.State.COOLDOWN, restarted.state())
        time += 59_999; assertEquals(ParentDomain.State.COOLDOWN, restarted.state())
        time++; assertNotNull(restarted.verify("012345".toCharArray(), restarted.enterPage()))
        assertEquals(0, store.read()!!.failures)
    }
    @Test fun exponentialPenaltyIsCapped() {
        val (d, page) = owned()
        repeat(8) { group ->
            repeat(5) { assertNull(d.verify("999999".toCharArray(), page)) }
            val expected = minOf(3_600_000L, 60_000L shl group)
            assertEquals(expected, store.read()!!.cooldownMs)
            time += expected
        }
    }
    @Test fun reservationIsCommittedBeforeKdfAndRevokeRejectsResult() {
        val (d, page) = owned()
        store.beforeCommit = { d.revoke() }
        assertNull(d.verify("012345".toCharArray(), page))
        assertEquals(1, store.read()!!.failures)
        assertEquals(ParentDomain.State.LOCKED, d.state())
    }
    @Test fun reservationDiskFailureDeniesAndQuarantines() {
        val (d, page) = owned(); store.failWrite = true
        assertNull(d.verify("012345".toCharArray(), page))
        assertEquals(ParentDomain.State.QUARANTINED, d.state())
    }
    @Test fun settingsDiskFailureRevokesAndPreservesPriorValue() {
        val (d, page) = owned(); val g = unlock(d, page); store.failWrite = true
        assertFalse(d.saveVolumeLimit(g, 80))
        assertNull(d.volumeLimit(g)); assertEquals(60, store.read()!!.volumeLimit)
        assertEquals(ParentDomain.State.QUARANTINED, d.state())
    }
    @Test fun authorizationExpiresDuringPreparedWrite() {
        val (d, page) = owned(); val g = unlock(d, page)
        store.beforeCommit = { time += 120_000 }
        assertFalse(d.saveVolumeLimit(g, 80)); assertEquals(60, store.read()!!.volumeLimit)
    }
    @Test fun corruptOrUnreadableStoreIsNeverUnowned() {
        store.bytes = ByteArray(72)
        assertEquals(ParentDomain.State.QUARANTINED, domain().state())
        store.bytes = null; store.failRead = true
        assertEquals(ParentDomain.State.QUARANTINED, domain().state())
    }
    @Test fun codecRejectsUnknownSchemaTruncationAndTrailingBytes() {
        owned(); val encoded = store.bytes!!
        for (invalid in listOf(encoded.copyOf(71), encoded + byteArrayOf(0), encoded.copyOf().also { it[3] = 2 })) {
            try { ParentCodec.decode(invalid); fail("invalid record accepted") } catch (_: IllegalStateException) {}
        }
    }
    @Test fun ownerProofCannotReplayOrSurvivePageChange() {
        val d = domain(); var page = d.enterPage()
        val proof = d.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN, page)!!
        d.revoke(); assertFalse(d.replacePin("012345".toCharArray(), proof, page))
        page = d.enterPage()
        val next = d.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN, page)!!
        assertTrue(d.replacePin("012345".toCharArray(), next, page))
        assertFalse(d.replacePin("012345".toCharArray(), next, page))
    }
    @Test fun expiredOrWrongOperationProofDenied() {
        val d = domain(); val page = d.enterPage()
        val wrong = d.beginOwnerOperation(OwnerOperation.PROVISION_ENDPOINT, page)!!
        assertFalse(d.replacePin("012345".toCharArray(), wrong, page))
        val expired = d.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN, page)!!
        time += 60_000; assertFalse(d.replacePin("012345".toCharArray(), expired, page))
    }
    @Test fun recoveryPreservesSettingsAndRevokesOldGrant() {
        val (d, page) = owned(); val g = unlock(d, page); assertTrue(d.saveVolumeLimit(g, 70))
        val proof = d.beginOwnerOperation(OwnerOperation.RESET_PIN, page)!!
        assertTrue(d.replacePin("123456".toCharArray(), proof, page))
        assertFalse(d.saveVolumeLimit(g, 80)); val next = d.enterPage()
        assertNull(d.verify("012345".toCharArray(), next))
        assertEquals(70, d.volumeLimit(d.verify("123456".toCharArray(), next)!!))
    }
    @Test fun workerGuardPreventsStorageAndHashOnUiThread() {
        try { ParentDomain(store, { time }, { error("worker required") }, binding = "test"); fail() }
        catch (_: IllegalStateException) { assertEquals(0, store.writes) }
    }
    @Test fun productionEnvelopeRejectsTamperingWrongBindingAndWrongKey() {
        owned()
        val key = javax.crypto.spec.SecretKeySpec(ByteArray(32) { 17 }, "AES")
        val aad = "synthetic-binding:v1".toByteArray()
        val sealed = ParentEnvelope.seal(store.bytes!!, key, aad)
        assertArrayEquals(store.bytes, ParentEnvelope.open(sealed, key, aad))
        val corrupt = listOf(sealed.copyOf().also { it[0] = (it[0].toInt() xor 1).toByte() },
            sealed.copyOf().also { it[30] = (it[30].toInt() xor 1).toByte() }, sealed.copyOf(20))
        for (bytes in corrupt) {
            try { ParentEnvelope.open(bytes, key, aad); fail("tamper accepted") } catch (_: Exception) {}
        }
        try { ParentEnvelope.open(sealed, key, "other-binding".toByteArray()); fail() }
        catch (_: java.security.GeneralSecurityException) {}
        try {
            ParentEnvelope.open(sealed, javax.crypto.spec.SecretKeySpec(ByteArray(32) { 18 }, "AES"), aad); fail()
        } catch (_: java.security.GeneralSecurityException) {}
        assertFalse(sealed.contentEquals(ParentEnvelope.seal(store.bytes!!, key, aad)))
    }
    @Test fun failedSuccessCommitNeverGrantsAndReservedFailureSurvivesRestart() {
        val (d, page) = owned(); var commits = 0
        store.beforeCommit = { commits++; if (commits == 2) error("synthetic disk fault") }
        assertNull(d.verify("012345".toCharArray(), page))
        assertEquals(1, store.read()!!.failures)
        assertEquals(ParentDomain.State.QUARANTINED, d.state())
        assertEquals(ParentDomain.State.LOCKED, domain().state())
    }
    @Test fun invalidLimitDoesNotWriteOrRefreshGrant() {
        val (d, page) = owned(); val g = unlock(d, page); val writes = store.writes
        time += 119_999; assertFalse(d.saveVolumeLimit(g, 101)); assertFalse(d.saveVolumeLimit(g, -1))
        assertEquals(writes, store.writes); time++; assertNull(d.volumeLimit(g))
    }
    @Test fun hashingCandidateTimingIsHostOnly() {
        val pin = "012345".toCharArray(); val samples = mutableListOf<Long>()
        repeat(4) {
            val start = System.nanoTime()
            PinHasher().derive(pin, ByteArray(16) { 1 }).fill(0)
            samples += (System.nanoTime() - start) / 1_000_000
        }
        pin.fill('\u0000')
        println("PBKDF2 host-only iterations=600000 samples_ms=" + samples.joinToString(","))
        assertEquals(4, samples.size)
    }
}
