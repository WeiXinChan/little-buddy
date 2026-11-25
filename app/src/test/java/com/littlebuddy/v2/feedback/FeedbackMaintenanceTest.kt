package com.littlebuddy.v2.feedback

import java.io.IOException
import java.nio.file.Files
import javax.crypto.KeyGenerator
import org.junit.Assert.*
import org.junit.Test

class FeedbackMaintenanceTest {
    private class Queue : FeedbackQueue {
        private val jobs = ArrayDeque<() -> Unit>()
        override fun post(action: () -> Unit) { synchronized(jobs) { jobs.addLast(action) } }
        fun drain() { while (true) (synchronized(jobs) { if (jobs.isEmpty()) null else jobs.removeFirst() } ?: return).invoke() }
    }
    private class Clock(var time: Long = 1000) : FeedbackClock { override fun now() = time }
    private class Auth : FeedbackPageAuthority {
        var alive = true; var epoch = 0
        private class Intent(val epoch: Int) : ParentIntent
        override fun current() = alive
        override fun invalidate() { epoch++ }
        override fun close() { alive = false; epoch++ }
        override fun prepare(operation: Operation, digest: String): ParentIntent? = if (alive) Intent(epoch) else null
        override fun accept(intent: ParentIntent, operation: Operation, digest: String, acceptance: () -> Unit): Boolean {
            if (!alive || (intent as Intent).epoch != epoch) return false
            acceptance(); return true
        }
    }
    private class FaultFiles(val base: VaultFiles) : VaultFiles {
        var fail = false
        override fun read(name: String) = base.read(name)
        override fun remove(name: String) = base.remove(name)
        override fun replace(name: String, bytes: ByteArray) {
            if (fail) throw IOException("synthetic write failure")
            base.replace(name, bytes)
        }
    }
    private class Rig : AutoCloseable {
        val dir = Files.createTempDirectory("m09-maintenance-").toFile()
        val store = java.io.File(dir, "data").apply { mkdirs() }
        val lease = java.io.File(dir, "owner")
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val files = FaultFiles(PrivateVaultFiles(store)); val clock = Clock()
        val work = Queue(); val ui = Queue()
        val seedAuth = Auth()
        val seedProvider = object : FeedbackProvider {
            override fun available() = true
            override fun submit(idempotencyKey: String, payload: FeedbackPayload, admit: () -> Boolean): SubmitReceipt {
                check(admit()); return SubmitReceipt(clock.time)
            }
            override fun withdraw(idempotencyKey: String) = DeleteReceipt(clock.time, false)
        }
        val seed = FeedbackCore(FeedbackVault(files, key), clock, seedAuth, seedProvider)
        val owner = FeedbackCoreOwner(lease, { FeedbackVault(files, key) }, clock)
        var coreOpens = 0; lateinit var core: FeedbackCore
        val engine = FeedbackEngine(work, ui, { a -> owner.open(a).also { core = it; coreOpens++ } })
        var installed = 0; lateinit var tick: () -> Unit
        var scheduleOk = true; var scheduleThrows = false; var checks = 0
        val maintenance = FeedbackMaintenance(work, engine, FeedbackJobSchedule {
            checks++; if (scheduleThrows) throw IOException("synthetic scheduling failure")
            scheduleOk
        }, FeedbackPeriodic { action -> installed++; tick = action })
        fun drain() { work.drain(); ui.drain() }
        fun record() = seed.record(mapOf("stage" to LogStage.CONNECT, "error" to LogError.NONE,
            "version" to 1, "elapsedMs" to 2L, "usage" to 3L, "PIN" to "SYNTHETIC_FORBIDDEN_VALUE"))
        fun submit(): String {
            seed.startDraft(Category.OTHER, "SYNTHETIC_MAINTENANCE_BODY")
            return seed.submit(seed.preview())
        }
        fun sourceCount(): Int {
            val bytes = FeedbackVault(files, key).load()!!
            return java.io.DataInputStream(bytes.inputStream()).use { it.readInt(); it.readLong(); it.readInt() }
        }
        fun durableBodyPresent(): Boolean = FeedbackVault(files, key).load()!!.toString(Charsets.UTF_8).contains("SYNTHETIC_MAINTENANCE_BODY")
        override fun close() { owner.close(); dir.deleteRecursively() }
    }
    @Test fun startupSweepWithoutAnyPageExpiresActualVaultAndPreservesMinimalLogs() = Rig().use { r ->
        r.record(); r.submit(); r.clock.time += WEEK
        r.maintenance.start(); r.drain()
        assertEquals(0, r.sourceCount()); assertFalse(r.durableBodyPresent())
        assertEquals(true, r.maintenance.lastSweepSucceeded); assertTrue(r.maintenance.jobScheduled)
        assertFalse(FeedbackVault(r.files, r.key).load()!!.toString(Charsets.UTF_8).contains("SYNTHETIC_FORBIDDEN_VALUE"))
    }
    @Test fun coldRestartReattachesSinglePeriodicAndCompensatesOverdueSweep() = Rig().use { r ->
        r.record(); r.submit(); r.clock.time += WEEK
        // New process runtime is created from the actual durable blobs; no Grant/page is reconstructed.
        r.maintenance.start(); r.maintenance.start(); r.drain()
        assertEquals(1, r.installed); assertEquals(1, r.coreOpens); assertFalse(r.durableBodyPresent())
        r.tick(); r.drain(); assertEquals(true, r.maintenance.lastSweepSucceeded); assertEquals(0, r.sourceCount())
    }
    @Test fun multipleConcurrentOsRequestsCoalesceActualSweepAndCompleteAllWaiters() = Rig().use { r ->
        r.record(); r.clock.time += WEEK
        val results = java.util.Collections.synchronizedList(mutableListOf<Boolean>())
        val threads = List(16) { Thread { r.maintenance.request { results.add(it) } } }
        threads.forEach { it.start() }; threads.forEach { it.join() }; r.drain()
        assertEquals(16, results.size); assertTrue(results.all { it })
        assertEquals(1, r.checks); assertEquals(1, r.coreOpens); assertEquals(0, r.sourceCount())
    }
    @Test fun matchingPersistedJobIsNotReplacedByServiceRestart() {
        var replacements = 0
        val registration = FeedbackJobRegistration({ true }, { replacements++; true })
        repeat(3) { assertTrue(registration.ensure()) }; assertEquals(0, replacements)
    }
    @Test fun absentOrMismatchedJobIsRegisteredAndFailureCanRetry() {
        var matched = false; var replacements = 0; var success = false
        val registration = FeedbackJobRegistration({ matched }, { replacements++; success.also { if (it) matched = true } })
        assertFalse(registration.ensure()); success = true; assertTrue(registration.ensure()); assertTrue(registration.ensure())
        assertEquals(2, replacements)
    }
    @Test fun schedulingFailureDoesNotBlockPhysicalSweepAndNextTickRetriesRegistration() = Rig().use { r ->
        r.record(); r.clock.time += WEEK; r.scheduleOk = false
        r.maintenance.start(); r.drain()
        assertFalse(r.maintenance.jobScheduled); assertEquals(true, r.maintenance.lastSweepSucceeded)
        assertEquals(0, r.sourceCount())
        r.scheduleOk = true; r.tick(); r.drain(); assertTrue(r.maintenance.jobScheduled)
    }
    @Test fun schedulingExceptionStillCleansRealVaultAndRecoversOnNextStartup() = Rig().use { r ->
        r.record(); r.clock.time += WEEK; r.scheduleThrows = true
        r.maintenance.start(); r.drain(); assertEquals(0, r.sourceCount()); assertFalse(r.maintenance.jobScheduled)
        r.scheduleThrows = false; r.maintenance.start(); r.drain()
        assertEquals(1, r.installed); assertTrue(r.maintenance.jobScheduled)
    }
    @Test fun realStoreLockConflictRefusesSecondWriterAndCanRetryAfterOwnerRelease() = Rig().use { r ->
        r.record(); r.clock.time += WEEK
        val other = FeedbackCoreOwner(r.lease, { FeedbackVault(r.files, r.key) }, r.clock)
        other.open(DenyParentAuthorizer)
        val before = r.files.read("materials")!!
        r.maintenance.start(); r.drain()
        assertEquals(false, r.maintenance.lastSweepSucceeded); assertEquals(0, r.coreOpens)
        assertArrayEquals(before, r.files.read("materials"))
        other.close(); r.tick(); r.drain()
        assertEquals(true, r.maintenance.lastSweepSucceeded); assertEquals(1, r.coreOpens); assertEquals(0, r.sourceCount())
    }
    object LeaseProbe {
        @JvmStatic fun main(args: Array<String>) {
            java.nio.channels.FileChannel.open(java.io.File(args.single()).toPath(),
                java.nio.file.StandardOpenOption.CREATE, java.nio.file.StandardOpenOption.WRITE).use { channel ->
                val lease = channel.tryLock()
                if (lease == null) println("BUSY") else { lease.release(); println("ACQUIRED") }
            }
        }
    }
    @Test fun productionOwnerExcludesAnotherJvmProcessAndReleasesOnTeardown() = Rig().use { r ->
        r.maintenance.start(); r.drain()
        fun child(): String {
            val process = ProcessBuilder(java.io.File(System.getProperty("java.home"), "bin/java").path,
                "-Xmx64m", "-cp", System.getProperty("java.class.path"),
                LeaseProbe::class.java.name, r.lease.path).redirectErrorStream(true).start()
            val completed = process.waitFor(10, java.util.concurrent.TimeUnit.SECONDS)
            if (!completed) process.destroyForcibly().waitFor()
            assertTrue("lock helper timed out", completed)
            val output = process.inputStream.bufferedReader().readText().trim()
            assertEquals(output, 0, process.exitValue()); return output
        }
        assertEquals("BUSY", child()); r.owner.close(); assertEquals("ACQUIRED", child())
    }
    @Test fun vaultCreationFailureReleasesActualOwnershipLock() = Rig().use { r ->
        val failed = FeedbackCoreOwner(r.lease, { throw FeedbackFailure(Failure.QUARANTINED) }, r.clock)
        try { failed.open(DenyParentAuthorizer); fail() } catch (e: FeedbackFailure) { assertEquals(Failure.QUARANTINED, e.reason) }
        r.maintenance.start(); r.drain(); assertEquals(true, r.maintenance.lastSweepSucceeded)
        failed.close()
    }
    @Test fun failedWriteReportsRetryAndRestartCanExpireActualFiles() = Rig().use { r ->
        r.record(); r.submit(); r.clock.time += WEEK; r.files.fail = true
        r.maintenance.start(); r.drain(); assertEquals(false, r.maintenance.lastSweepSucceeded)
        r.files.fail = false; r.tick(); r.drain(); assertEquals(true, r.maintenance.lastSweepSucceeded)
        assertFalse(r.durableBodyPresent()); assertEquals(0, r.sourceCount())
    }
    @Test fun liveCoreWriteFailureStaysQuarantinedInsteadOfSilentlyReopening() = Rig().use { r ->
        r.record(); r.maintenance.start(); r.drain(); assertEquals(1, r.coreOpens)
        r.clock.time += WEEK; r.files.fail = true; r.tick(); r.drain()
        assertEquals(false, r.maintenance.lastSweepSucceeded)
        r.files.fail = false; r.tick(); r.drain()
        assertEquals(false, r.maintenance.lastSweepSucceeded); assertEquals(1, r.coreOpens)
        // Controlled process teardown releases the owner; fresh runtime can then compensate.
        r.owner.close()
        val nextOwner = FeedbackCoreOwner(r.lease, { FeedbackVault(r.files, r.key) }, r.clock)
        try { nextOwner.open(DenyParentAuthorizer); assertEquals(0, r.sourceCount()) }
        finally { nextOwner.close() }
    }
    @Test fun partialExpiryKeepsNewerSourceWhileExpiredIssuePayloadIsRemoved() = Rig().use { r ->
        r.record(); r.submit(); r.clock.time += 100; r.record(); r.clock.time = 1000 + WEEK
        r.maintenance.start(); r.drain(); assertEquals(1, r.sourceCount()); assertFalse(r.durableBodyPresent())
    }
    @Test fun revokedPageDoesNotGateBackgroundExpiryOrRestoreItsUi() = Rig().use { r ->
        val id = r.submit(); r.clock.time += WEEK - 1
        val auth = Auth(); val screens = mutableListOf<FeedbackScreen>()
        val page = r.engine.open(auth, screens::add); r.drain(); page.detail(id); r.drain()
        auth.close(); r.clock.time++; r.maintenance.start(); r.drain()
        assertSame(FeedbackScreen.Locked, screens.last()); assertFalse(r.durableBodyPresent()); page.close()
    }
    @Test fun stoppedOsJobCannotCompleteOrCancelNewJobCallback() = Rig().use { r ->
        r.record(); r.clock.time += WEEK
        val results = mutableListOf<Pair<Any, Boolean>>()
        val runs = FeedbackJobRuns(r.maintenance, r.ui) { p: Any, retry -> results.add(p to retry) }
        val old = Any(); val newer = Any()
        runs.start(old); runs.stop(old); runs.start(newer); runs.stop(old); r.drain()
        assertEquals(1, results.size); assertSame(newer, results.single().first); assertFalse(results.single().second)
        assertEquals(0, r.sourceCount())
    }
    @Test fun osFailedJobFinishesExactlyOnceWithRetry() = Rig().use { r ->
        r.files.fail = true
        val results = mutableListOf<Boolean>()
        val runs = FeedbackJobRuns<Any>(r.maintenance, r.ui) { _, retry -> results.add(retry) }
        runs.start(Any()); r.drain(); assertEquals(listOf(true), results)
        r.ui.drain(); assertEquals(1, results.size)
    }
    @Test fun backgroundRegistrationIoCannotCancelEditorRequestedAfterTick() = Rig().use { r ->
        val id = r.submit(); r.clock.time += WEEK - 1
        val screens = mutableListOf<FeedbackScreen>(); val page = r.engine.open(Auth(), screens::add)
        r.drain(); page.detail(id); r.work.drain(); val before = screens.size
        r.clock.time++; r.files.fail = true
        r.maintenance.request(); page.edit(); r.drain()
        assertTrue(screens.last() is FeedbackScreen.Editor)
        assertFalse(screens.drop(before).any { it is FeedbackScreen.Detail && it.item.description != null })
        page.close()
    }
    @Test fun offlineWithdrawalKeepsPayloadFreeOutboxAndEarlierDeadline() = Rig().use { r ->
        val id = r.submit(); r.seed.withdraw(id); r.clock.time += DAY
        r.maintenance.start(); r.drain(); assertFalse(r.durableBodyPresent()); r.owner.close()
        val reopened = FeedbackCore(FeedbackVault(r.files, r.key), r.clock, Auth())
        val view = reopened.list().single()
        assertEquals(1000 + DAY, view.deleteBy); assertEquals(1000L, view.submittedAt)
        assertNotEquals(FeedbackState.DELETED, view.state); assertNull(view.description)
        assertTrue(r.files.read("ledger")!!.isNotEmpty()) // no remote receipt was fabricated
    }
    @Test fun noProviderNeverBecomesAcceptedBySystemSweep() = Rig().use { r ->
        r.submit(); r.clock.time += WEEK
        r.maintenance.start(); r.drain()
        assertEquals(false, r.engine.providerAvailable()); assertFalse(r.durableBodyPresent())
    }
}
