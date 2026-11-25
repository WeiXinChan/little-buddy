package com.littlebuddy.v2.feedback

import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.nio.file.Files
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import javax.crypto.KeyGenerator

class FeedbackCoreTest {
    private class Clock(var time: Long = 1000) : FeedbackClock {
        var trusted = true
        override fun now(): Long? = if (trusted) time else null
    }
    private class Auth : ParentAuthorizer {
        @Volatile var generation = 1
        private class Intent(val generation: Int, val op: Operation, val scope: String) : ParentIntent
        override fun prepare(operation: Operation, digest: String): ParentIntent? =
            if (generation > 0) Intent(generation, operation, digest) else null
        override fun accept(intent: ParentIntent, operation: Operation, digest: String, acceptance: () -> Unit): Boolean {
            val value = intent as? Intent ?: return false
            if (value.generation != generation || generation == 0 || value.op != operation || value.scope != digest) return false
            acceptance(); return true
        }
        fun revoke() { generation = 0 }
    }
    private class Provider(val clock: Clock) : FeedbackProvider {
        var enabled = true
        var fail = false
        var deleted = true
        var beforeAdmission: (() -> Unit)? = null
        var afterAdmission: (() -> Unit)? = null
        val objects = mutableMapOf<String, FeedbackPayload>()
        val keys = mutableListOf<String>()
        var receivedLogs = byteArrayOf()
        override fun available() = enabled
        override fun submit(idempotencyKey: String, payload: FeedbackPayload, admit: () -> Boolean): SubmitReceipt {
            beforeAdmission?.invoke()
            if (!admit()) throw FeedbackFailure(Failure.DENIED)
            keys.add(idempotencyKey)
            receivedLogs = payload.logs.copyOf()
            objects.putIfAbsent(idempotencyKey, payload)
            val original = clock.time
            afterAdmission?.invoke()
            if (fail) throw FeedbackFailure(Failure.NETWORK)
            return SubmitReceipt(original)
        }
        override fun withdraw(idempotencyKey: String): DeleteReceipt {
            if (fail) throw FeedbackFailure(Failure.NETWORK)
            if (deleted) objects.remove(idempotencyKey)
            return DeleteReceipt(clock.time, deleted)
        }
    }
    private class FaultFiles(val base: VaultFiles) : VaultFiles {
        var fail = false
        var beforeWrite: (() -> Unit)? = null
        override fun read(name: String) = base.read(name)
        override fun replace(name: String, bytes: ByteArray) {
            beforeWrite?.invoke()
            if (fail) throw java.io.IOException("SYNTHETIC_SECRET_NOT_FOR_ERRORS")
            base.replace(name, bytes)
        }
        override fun remove(name: String) = base.remove(name)
    }
    private class Rig : AutoCloseable {
        val dir = Files.createTempDirectory("m09-test-").toFile()
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val files = FaultFiles(PrivateVaultFiles(dir))
        val clock = Clock()
        val auth = Auth()
        val provider = Provider(clock)
        var core = FeedbackCore(FeedbackVault(files, key), clock, auth, provider)
        fun restart() { core = FeedbackCore(FeedbackVault(files, key), clock, auth, provider) }
        fun send(logs: Boolean = false): String {
            core.startDraft(Category.OTHER, "synthetic description")
            if (logs) core.selectLogs(0, clock.time)
            return core.submit(core.preview())
        }
        override fun close() { dir.deleteRecursively() }
    }
    private fun failure(reason: Failure, action: () -> Unit) {
        try { action(); fail("Expected $reason") } catch (error: FeedbackFailure) { assertEquals(reason, error.reason) }
    }
    private fun fields(extra: Map<String, Any?> = emptyMap()): Map<String, Any?> = mapOf(
        "stage" to LogStage.PLAY, "error" to LogError.NONE, "version" to 1, "elapsedMs" to 25L, "usage" to 2L) + extra

    @Test fun productionDefaultsDeny() = Rig().use { r ->
        val core = FeedbackCore(FeedbackVault(r.files, r.key), r.clock)
        failure(Failure.DENIED) { core.startDraft(Category.OTHER, "text") }
        failure(Failure.DENIED) { core.list() }
        failure(Failure.DENIED) { core.clearLogs() }
    }
    @Test fun productionProviderUnavailableDoesNotSend() = Rig().use { r ->
        val core = FeedbackCore(FeedbackVault(r.files, r.key), r.clock, r.auth)
        core.startDraft(Category.OTHER, "text")
        failure(Failure.UNAVAILABLE) { core.submit(core.preview()) }
        assertTrue(core.list().isEmpty())
    }
    @Test fun unknownAndWrongTypeLogFieldsNeverPersistOrExport() = Rig().use { r ->
        val sentinel = "SYNTHETIC_SECRET_NOT_A_REAL_CREDENTIAL"
        r.core.record(fields(mapOf("exception" to sentinel, "prompt" to sentinel, "url" to sentinel)))
        r.core.record(fields(mapOf("usage" to sentinel)))
        r.send(true)
        val log = r.provider.receivedLogs.toString(Charsets.US_ASCII)
        assertFalse(log.contains(sentinel)); assertEquals(1, log.lines().count { it.isNotBlank() })
        for (file in r.dir.listFiles()!!) assertFalse(file.readBytes().toString(Charsets.ISO_8859_1).contains(sentinel))
    }
    @Test fun pureDescriptionIsDefault() = Rig().use { r ->
        r.core.record(fields()); r.send(); assertEquals(0, r.provider.receivedLogs.size)
    }
    @Test fun exactPreviewAndChangedDescriptionInvalidate() = Rig().use { r ->
        r.core.record(fields()); r.core.startDraft(Category.IMAGE, "text"); r.core.selectLogs(1000, 1000)
        val token = r.core.preview()
        assertEquals(1, token.logs.count); assertEquals(1000L, token.logs.from); assertTrue(token.logs.bytes > 0)
        r.core.editDescription("changed")
        failure(Failure.STALE) { r.core.submit(token) }
        assertTrue(r.provider.objects.isEmpty())
    }
    @Test fun changedSelectionAndReconfirmationInvalidateOldToken() = Rig().use { r ->
        r.core.record(fields()); r.core.startDraft(Category.OTHER, "text")
        val first = r.core.preview(); r.core.selectLogs(0, 1000)
        failure(Failure.STALE) { r.core.submit(first) }
        val second = r.core.preview(); val third = r.core.preview()
        failure(Failure.STALE) { r.core.submit(second) }; r.core.submit(third); Unit
    }
    @Test fun draftCancelAndRestartNeverRestoreText() = Rig().use { r ->
        r.core.startDraft(Category.OTHER, "SYNTHETIC_DRAFT")
        val token = r.core.preview(); r.core.cancelDraft()
        failure(Failure.STALE) { r.core.submit(token) }
        r.restart(); failure(Failure.INVALID) { r.core.preview() }
    }
    @Test fun unicodeLimitUsesCharacters() = Rig().use { r ->
        r.core.startDraft(Category.OTHER, "😀".repeat(2000))
        failure(Failure.INVALID) { r.core.editDescription("😀".repeat(2001)) }
    }
    @Test fun staleGrantAfterBlockedDiskCannotAdmit() = Rig().use { r ->
        r.core.startDraft(Category.OTHER, "text"); val token = r.core.preview()
        val blocked = CountDownLatch(1); val release = CountDownLatch(1)
        r.files.beforeWrite = { blocked.countDown(); check(release.await(3, TimeUnit.SECONDS)) }
        val error = AtomicReference<FeedbackFailure?>()
        val worker = Thread { try { r.core.submit(token) } catch (failure: FeedbackFailure) { error.set(failure) } }
        val before = File(r.dir, "materials").readBytes()
        worker.start(); assertTrue(blocked.await(3, TimeUnit.SECONDS))
        r.auth.revoke() // does not acquire the core/IO monitor
        release.countDown(); worker.join(4000); assertFalse(worker.isAlive)
        assertEquals(Failure.DENIED, error.get()?.reason)
        assertArrayEquals(before, File(r.dir, "materials").readBytes())
        r.files.beforeWrite = null; r.auth.generation = 2; r.restart(); assertTrue(r.core.list().isEmpty())
        assertTrue(r.provider.objects.isEmpty())
    }
    @Test fun blockedClearRevocationPreservesDurableSourceLogs() = Rig().use { r ->
        r.core.record(fields())
        val before = File(r.dir, "materials").readBytes()
        val blocked = CountDownLatch(1); val release = CountDownLatch(1)
        val error = AtomicReference<FeedbackFailure?>()
        r.files.beforeWrite = { blocked.countDown(); check(release.await(3, TimeUnit.SECONDS)) }
        val worker = Thread { try { r.core.clearLogs() } catch (failure: FeedbackFailure) { error.set(failure) } }
        worker.start(); assertTrue(blocked.await(3, TimeUnit.SECONDS)); r.auth.revoke()
        release.countDown(); worker.join(4000); assertFalse(worker.isAlive)
        assertEquals(Failure.DENIED, error.get()?.reason)
        assertArrayEquals(before, File(r.dir, "materials").readBytes())
        r.files.beforeWrite = null; r.auth.generation = 2; r.restart()
        r.core.startDraft(Category.OTHER, "text"); r.core.selectLogs(0, r.clock.time)
        assertEquals(1, r.core.preview().logs.count)
    }
    @Test fun revocationAfterLegalCommitReportsThatTransaction() = Rig().use { r ->
        r.core.record(fields())
        var writes = 0
        r.files.beforeWrite = { writes++; if (writes == 2) r.auth.revoke() }
        r.core.clearLogs() // staging complete, final state published before the second write
        r.files.beforeWrite = null; r.auth.generation = 2; r.restart()
        r.core.startDraft(Category.OTHER, "text"); r.core.selectLogs(0, r.clock.time)
        assertEquals(0, r.core.preview().logs.count)
    }
    @Test fun revokedAtNetworkAdmissionCannotSubmit() = Rig().use { r ->
        r.provider.beforeAdmission = { r.auth.revoke() }; r.send()
        assertTrue(r.provider.objects.isEmpty())
    }
    @Test fun withdrawnDuringUploadWinsOverLateReceipt() = Rig().use { r ->
        r.provider.afterAdmission = {
            val id = r.core.list().single().id
            r.core.withdraw(id)
        }
        val id = r.send(true)
        val view = r.core.list().single()
        assertEquals(FeedbackState.DELETE_PENDING, view.state); assertNull(view.description)
        r.core.drainDeletions(); assertFalse(r.provider.objects.containsKey(id))
        assertEquals(FeedbackState.DELETED, r.core.list().single().state)
    }
    @Test fun partialUploadTimeoutDeletedByOriginalKey() = Rig().use { r ->
        r.provider.fail = true; val id = r.send()
        assertEquals(FeedbackState.SEND_FAILED, r.core.list().single().state)
        assertTrue(r.provider.objects.containsKey(id)); r.core.withdraw(id)
        r.provider.fail = false; r.core.drainDeletions()
        assertTrue(r.provider.objects.isEmpty()); assertEquals(listOf(id), r.provider.keys)
    }
    @Test fun withdrawRetryDoesNotExtendDeadlineAndSurvivesRestart() = Rig().use { r ->
        r.send(); r.clock.time += DAY; r.core.withdraw(r.core.list().single().id)
        val original = r.core.list().single().deleteBy
        r.clock.time += HOUR; r.restart(); r.core.withdraw(r.core.list().single().id)
        assertEquals(original, r.core.list().single().deleteBy)
        r.core.drainDeletions(); assertTrue(r.provider.objects.isEmpty())
    }
    @Test fun firstDayWithdrawalRejectsAtSecondDayBoundary() = Rig().use { r ->
        val id = r.send(); val base = r.clock.time; r.clock.time = base + DAY; r.core.withdraw(id)
        r.clock.time = base + 2 * DAY - 1; assertEquals(base + 2 * DAY, r.core.list().single().deleteBy)
        r.clock.time++; assertNull(r.core.list().single().description)
        r.core.receiveReply(id, "late reply"); assertNull(r.core.list().single().reply)
    }
    @Test fun sixthDayWithdrawalUsesOriginalSeventhDay() = Rig().use { r ->
        val id = r.send(); val base = r.clock.time
        r.clock.time = base + 6 * DAY + 23 * HOUR; r.core.withdraw(id)
        assertEquals(base + WEEK, r.core.list().single().deleteBy)
        r.clock.time = base + WEEK; assertTrue(r.core.list().isEmpty())
    }
    @Test fun replyDoesNotRenewOriginalSubmission() = Rig().use { r ->
        val id = r.send(); val original = r.core.list().single().deleteBy
        r.clock.time += 6 * DAY; r.core.receiveReply(id, "synthetic reply")
        assertEquals(original, r.core.list().single().deleteBy)
        assertEquals(FeedbackState.REPLIED, r.core.list().single().state)
    }
    @Test fun sourceClearDoesNotDeleteSubmittedCopyOrOtherFiles() = Rig().use { r ->
        val unrelated = File(r.dir.parentFile, r.dir.name + ".pin")
        try {
            unrelated.writeText("SYNTHETIC_PAIRING")
            r.core.record(fields()); r.send(true); r.core.clearLogs()
            assertEquals("synthetic description", r.core.list().single().description)
            r.core.startDraft(Category.OTHER, "new"); r.core.selectLogs(0, r.clock.time)
            assertEquals(0, r.core.preview().logs.count)
            assertTrue(r.provider.receivedLogs.isNotEmpty()); assertEquals("SYNTHETIC_PAIRING", unrelated.readText())
        } finally { unrelated.delete() }
    }
    @Test fun withdrawDoesNotClearSourceLogsOrOtherIssue() = Rig().use { r ->
        r.core.record(fields()); val first = r.send(true); r.send(); r.core.withdraw(first)
        assertEquals(1, r.core.list().count { it.description != null })
        r.core.startDraft(Category.OTHER, "third"); r.core.selectLogs(0, r.clock.time)
        assertEquals(1, r.core.preview().logs.count)
    }
    @Test fun exactSevenDayLogExpiryAndSelectedCopyTokenExpiry() = Rig().use { r ->
        r.core.record(fields()); r.core.startDraft(Category.OTHER, "text"); r.core.selectLogs(0, r.clock.time)
        val token = r.core.preview(); r.clock.time += WEEK
        failure(Failure.STALE) { r.core.submit(token) }
        r.core.sweep(); r.core.selectLogs(0, r.clock.time); assertEquals(0, r.core.preview().logs.count)
    }
    @Test fun selectedCopyDoesNotRenewSourceLogBirthTime() = Rig().use { r ->
        val base = r.clock.time
        r.core.record(fields()); r.clock.time += 6 * DAY; r.send(true)
        val vault = FeedbackVault(r.files, r.key)
        assertTrue(vault.load()!!.toString(Charsets.UTF_8).contains(",PLAY,NONE,"))
        r.clock.time = base + WEEK; r.core.sweep()
        assertFalse(vault.load()!!.toString(Charsets.UTF_8).contains(",PLAY,NONE,"))
        assertEquals("synthetic description", r.core.list().single().description)
    }
    @Test fun logRingEnforcesThousandCountAndBytes() = Rig().use { r ->
        repeat(1001) { r.core.record(fields()) }
        r.core.startDraft(Category.OTHER, "text"); r.core.selectLogs(0, r.clock.time)
        val preview = r.core.preview().logs
        assertEquals(1000, preview.count); assertTrue(preview.bytes <= 256 * 1024)
    }
    @Test fun missingLedgerRejectsOldPreWithdrawalSnapshotL8701() = Rig().use { r ->
        val id = r.send(); val snapshot = File(r.dir, "materials").readBytes()
        r.clock.time += DAY; r.core.withdraw(id); r.clock.time += DAY
        File(r.dir, "materials").writeBytes(snapshot); File(r.dir, "ledger").delete()
        failure(Failure.QUARANTINED) { r.restart() }
    }
    @Test fun oldMaterialsWithCurrentLedgerRejectedBeforeRead() = Rig().use { r ->
        val id = r.send(); val old = File(r.dir, "materials").readBytes()
        r.core.withdraw(id); File(r.dir, "materials").writeBytes(old)
        failure(Failure.QUARANTINED) { r.restart() }
    }
    @Test fun fullSnapshotImportMustBeQuarantined() = Rig().use { r ->
        r.send()
        val vault = FeedbackVault(r.files, r.key); vault.quarantineRestore()
        failure(Failure.QUARANTINED) { FeedbackCore(vault, r.clock, r.auth, r.provider) }
    }
    @Test fun corruptCiphertextOrWrongKeyRejected() = Rig().use { r ->
        r.send(); val file = File(r.dir, "materials"); val bytes = file.readBytes(); bytes[15] = (bytes[15].toInt() xor 1).toByte()
        file.writeBytes(bytes); failure(Failure.QUARANTINED) { r.restart() }
        val otherKey = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        failure(Failure.QUARANTINED) { FeedbackCore(FeedbackVault(r.files, otherKey), r.clock, r.auth) }
    }
    @Test fun deletionWriteFailureCannotReportSuccessOrExposeCachedText() = Rig().use { r ->
        val id = r.send(); r.files.fail = true
        failure(Failure.STORAGE) { r.core.withdraw(id) }
        r.files.fail = false
        assertEquals("synthetic description", r.core.list().single().description)
        assertTrue(r.provider.objects.containsKey(id)) // failed BEFORE commit, no false delete result
    }
    @Test fun interruptedTwoFilePublicationQuarantinesRestart() = Rig().use { r ->
        r.send()
        var writes = 0
        r.files.beforeWrite = { writes++; if (writes == 3) r.files.fail = true }
        failure(Failure.STORAGE) { r.core.clearLogs() }
        r.files.fail = false; r.files.beforeWrite = null
        failure(Failure.QUARANTINED) { r.restart() }
    }
    @Test fun deleteFailureAndPartialReceiptNeverClaimAllCopiesDeleted() = Rig().use { r ->
        val id = r.send(); r.core.withdraw(id)
        r.provider.fail = true; r.core.drainDeletions()
        assertEquals(FeedbackState.DELETE_FAILED, r.core.list().single().state)
        r.provider.fail = false; r.provider.deleted = false; r.core.drainDeletions()
        assertEquals(FeedbackState.DELETING, r.core.list().single().state)
        assertTrue(r.provider.objects.containsKey(id))
    }
    @Test fun expiredUnknownUploadStillHasPayloadFreeDeletionIntent() = Rig().use { r ->
        r.provider.fail = true; r.send(); r.clock.time += HOUR; r.core.sweep(); r.restart()
        assertNull(r.core.list().single().description)
        r.provider.fail = false; r.core.drainDeletions(); assertTrue(r.provider.objects.isEmpty())
    }
    @Test fun lateSubmitAfterOneHourNeverRestoresExpiredPayload() = Rig().use { r ->
        r.provider.afterAdmission = { r.clock.time += HOUR }
        r.send(); assertNull(r.core.list().single().description)
        assertEquals(FeedbackState.DELETE_PENDING, r.core.list().single().state)
    }
    @Test fun rollbackAndUntrustedClockRejectAccess() = Rig().use { r ->
        r.send(); r.clock.time--; failure(Failure.CLOCK) { r.core.list() }
        r.clock.trusted = false; failure(Failure.CLOCK) { r.core.list() }
    }
    @Test fun restartDoesNotAutomaticallyResubmitAndOldConfirmationIsInvalid() = Rig().use { r ->
        r.send(); r.core.startDraft(Category.OTHER, "draft"); val token = r.core.preview()
        r.restart(); assertEquals(1, r.provider.keys.size)
        failure(Failure.STALE) { r.core.submit(token) }
    }
}
