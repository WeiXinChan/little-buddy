package com.littlebuddy.v2.feedback

import java.io.File
import java.nio.file.Files
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import javax.crypto.KeyGenerator
import org.junit.Assert.*
import org.junit.Test

class Review39Probe {
    class Clock(var t: Long = 1000L) : FeedbackClock { override fun now() = t }
    class Auth : ParentAuthorizer {
        private var epoch = 1
        private class Ticket(val epoch: Int, val op: Operation, val scope: String) : ParentIntent
        @Synchronized override fun prepare(operation: Operation, digest: String): ParentIntent = Ticket(epoch, operation, digest)
        @Synchronized override fun accept(intent: ParentIntent, operation: Operation, digest: String, acceptance: () -> Unit): Boolean {
            val t = intent as? Ticket ?: return false
            if (t.epoch != epoch || t.op != operation || t.scope != digest) return false
            acceptance(); return true
        }
        @Synchronized fun revoke() { epoch++ }
    }
    class Provider(val c: Clock) : FeedbackProvider {
        var before: (() -> Unit)? = null
        var count = 0
        var payload = byteArrayOf()
        override fun available() = true
        override fun submit(idempotencyKey: String, payload: FeedbackPayload, admit: () -> Boolean): SubmitReceipt {
            before?.invoke()
            if (!admit()) throw FeedbackFailure(Failure.DENIED)
            count++; this.payload = payload.logs.copyOf()
            return SubmitReceipt(c.t)
        }
        override fun withdraw(idempotencyKey: String) = DeleteReceipt(c.t, true)
    }
    class FilesPort(val base: VaultFiles) : VaultFiles {
        var blockName: String? = null
        val reached = CountDownLatch(1)
        val release = CountDownLatch(1)
        override fun read(name: String) = base.read(name)
        override fun remove(name: String) = base.remove(name)
        override fun replace(name: String, bytes: ByteArray) {
            if (blockName == name) { reached.countDown(); check(release.await(5, TimeUnit.SECONDS)) }
            base.replace(name, bytes)
        }
    }
    class Rig : AutoCloseable {
        val dir = Files.createTempDirectory("qa39-independent-").toFile()
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val f = FilesPort(PrivateVaultFiles(dir)); val c = Clock(); val a = Auth(); val p = Provider(c)
        var core = FeedbackCore(FeedbackVault(f,key),c,a,p)
        fun record() { core.record(mapOf("stage" to LogStage.PLAY,"error" to LogError.NONE,"version" to 7,"elapsedMs" to 12L,"usage" to 3L)) }
        fun restart() { core = FeedbackCore(FeedbackVault(f,key),c,a,p) }
        fun confirmation(): Confirmation { core.startDraft(Category.OTHER,"synthetic-only"); return core.preview() }
        override fun close() { dir.deleteRecursively() }
    }
    @Test fun exactPreviewBytesAndRangeIndependentOracle() { Rig().use { r ->
        r.record(); r.c.t=1001; r.record(); r.core.startDraft(Category.OTHER,"synthetic")
        r.core.selectLogs(1000,1000); val x = r.core.preview()
        val expected="1000,PLAY,NONE,7,12,3\n".toByteArray(Charsets.US_ASCII)
        assertEquals(1000L,x.logs.from); assertEquals(1000L,x.logs.through)
        assertEquals(1,x.logs.count); assertEquals(expected.size,x.logs.bytes)
        r.core.submit(x); assertArrayEquals(expected,r.p.payload)
    } }
    private fun blockedBeforeDecision(clear: Boolean) { Rig().use { r ->
        r.record(); val token=r.confirmation(); val old=File(r.dir,"materials").readBytes()
        r.f.blockName="staging"; val failure=AtomicReference<Throwable?>()
        val worker=Thread { try { if(clear) r.core.clearLogs() else r.core.submit(token) } catch(t: Throwable) {failure.set(t)} }
        val revoker=Thread {r.a.revoke()}
        worker.start()
        try {
            assertTrue(r.f.reached.await(5,TimeUnit.SECONDS)); revoker.start(); revoker.join(300)
            assertFalse("revocation waits for IO",revoker.isAlive)
        } finally {r.f.release.countDown(); worker.join(5000); revoker.join(5000)}
        assertFalse(worker.isAlive); assertEquals(Failure.DENIED,(failure.get() as FeedbackFailure).reason)
        assertArrayEquals(old,File(r.dir,"materials").readBytes()); assertEquals(0,r.p.count)
        r.f.blockName=null; r.restart(); assertTrue(r.core.list().isEmpty())
        r.core.startDraft(Category.OTHER,"after"); r.core.selectLogs(0,r.c.t)
        assertEquals(1,r.core.preview().logs.count)
    } }
    @Test fun blockedSubmitBeforeDecisionRefusesDurableOutbox() { blockedBeforeDecision(false) }
    @Test fun blockedClearBeforeDecisionPreservesRestartLogs() { blockedBeforeDecision(true) }
    @Test fun blockedProviderAdmissionRechecksAfterRevoke() { Rig().use { r ->
        val reached=CountDownLatch(1); val release=CountDownLatch(1)
        r.p.before={reached.countDown(); check(release.await(5,TimeUnit.SECONDS))}
        val token=r.confirmation(); val failure=AtomicReference<Throwable?>()
        val worker=Thread {try {r.core.submit(token)}catch(t:Throwable){failure.set(t)}}
        worker.start(); try {assertTrue(reached.await(5,TimeUnit.SECONDS)); r.a.revoke()}
        finally {release.countDown();worker.join(5000)}
        assertNull(failure.get()); assertEquals(0,r.p.count)
        r.restart(); assertEquals(FeedbackState.SEND_FAILED,r.core.list().single().state)
    } }
    @Test fun revokedAfterCommitPersistsSpecificTransaction() { Rig().use { r ->
        r.record(); r.f.blockName="ledger"; val failure=AtomicReference<Throwable?>()
        val worker=Thread {try {r.core.clearLogs()}catch(t:Throwable){failure.set(t)}}
        worker.start(); try {assertTrue(r.f.reached.await(5,TimeUnit.SECONDS)); r.a.revoke()}
        finally {r.f.release.countDown();worker.join(5000)}
        assertNull(failure.get());r.f.blockName=null;r.restart()
        r.core.startDraft(Category.OTHER,"after");r.core.selectLogs(0,r.c.t)
        assertEquals(0,r.core.preview().logs.count)
    } }
    @Test fun unknownFieldsAbsentInDecryptedPersistentData() { Rig().use {r ->
        r.core.record(mapOf("stage" to LogStage.PLAY,"error" to LogError.NONE,"version" to 7,"elapsedMs" to 12L,"usage" to 3L,"prompt" to "QA39_SYNTHETIC_SECRET"))
        val plaintext=FeedbackVault(r.f,r.key).load()!!.toString(Charsets.ISO_8859_1)
        assertFalse(plaintext.contains("QA39_SYNTHETIC_SECRET"))
    } }
    @Test fun expiredSelectedDraftCopyMustBeReleasedBySweep() { Rig().use {r ->
        r.record();r.core.startDraft(Category.OTHER,"synthetic");r.core.selectLogs(0,r.c.t);r.core.preview()
        val field=FeedbackCore::class.java.getDeclaredField("draft").apply{isAccessible=true}
        val draft=field.get(r.core)
        val logField=draft.javaClass.getDeclaredField("logs").apply{isAccessible=true}
        assertTrue((logField.get(draft) as ByteArray).isNotEmpty())
        r.c.t+=WEEK;r.core.sweep()
        val after=field.get(r.core)
        assertTrue("R87-01: sweep retains expired selected log copy in active draft",after==null || (logField.get(after) as ByteArray).isEmpty())
    } }
}
