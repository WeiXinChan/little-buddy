package com.littlebuddy.v2.feedback

import com.littlebuddy.v2.parent.*
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.nio.file.Files
import javax.crypto.KeyGenerator

class FeedbackFlowTest {
    private class Queue : FeedbackQueue {
        val pending = ArrayDeque<() -> Unit>()
        override fun post(action: () -> Unit) { pending.addLast(action) }
        fun drain() { while (pending.isNotEmpty()) pending.removeFirst()() }
    }
    private class Clock(var time: Long = 1000L) : FeedbackClock { override fun now() = time }
    private class Authority : FeedbackPageAuthority {
        var epoch = 1; var alive = true
        private class Intent(val owner: Authority, val epoch: Int) : ParentIntent
        override fun current() = alive
        override fun prepare(operation: Operation, digest: String): ParentIntent? = if (alive) Intent(this, epoch) else null
        override fun accept(intent: ParentIntent, operation: Operation, digest: String, acceptance: () -> Unit): Boolean {
            val value = intent as? Intent ?: return false
            if (!alive || value.owner !== this || value.epoch != epoch) return false
            acceptance(); return true
        }
        override fun close() { alive = false; epoch++ }
        override fun invalidate() { epoch++ }
    }
    private class Provider(val clock: Clock) : FeedbackProvider {
        var beforeReadReturn: (() -> Unit)?=null
        var reply="";private val submitted=mutableMapOf<String,Long>()
        var enabled = true; var submitCount = 0; var withdrawCount = 0
        var beforeAdmit: (() -> Unit)? = null
        override fun available() = enabled
        override fun submit(idempotencyKey: String, payload: FeedbackPayload, admit: () -> Boolean): SubmitReceipt {
            beforeAdmit?.invoke()
            if (!admit()) throw FeedbackFailure(Failure.DENIED)
            submitCount++;submitted[idempotencyKey]=clock.time; return SubmitReceipt(clock.time)
        }
        override fun read(key: String,binding:String?,admit:(()->Unit)->Boolean):FeedbackRemote {
            if(!admit {})throw FeedbackFailure(Failure.DENIED)
            val original=submitted.getValue(key);beforeReadReturn?.invoke()
            return FeedbackRemote(original,original+WEEK,if(reply.isEmpty())FeedbackState.SUBMITTED else FeedbackState.REPLIED,reply)
        }
        override fun withdraw(idempotencyKey: String): DeleteReceipt { withdrawCount++; return DeleteReceipt(clock.time, true) }
    }
    private class Rig : AutoCloseable {
        val dir = Files.createTempDirectory("m09-flow-").toFile()
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val disk=PrivateVaultFiles(dir);var onStage:(()->Unit)?=null
        val files=object:VaultFiles by disk {override fun replace(name:String,bytes:ByteArray){disk.replace(name,bytes);if(name=="staging")onStage?.invoke()} }
        val clock = Clock(); val auth = Authority(); val provider = Provider(clock)
        val work = Queue(); val ui = Queue(); val screens = mutableListOf<FeedbackScreen>()
        lateinit var core: FeedbackCore
        val engine = FeedbackEngine(work, ui, { router -> FeedbackCore(FeedbackVault(files, key), clock, router, provider).also { core = it } }, { provider.enabled })
        val controller = engine.open(auth, screens::add)
        fun drain() { work.drain(); ui.drain() }
        fun preview() { controller.preview(Category.OTHER, "synthetic parent description", null, null); drain() }
        fun send(): String {
            preview(); controller.submit(); drain()
            return (screens.last() as FeedbackScreen.Issues).items.single().id
        }
        override fun close() { controller.close(); dir.deleteRecursively() }
    }
    @Test fun unavailableProviderShowsExplicitCapabilityAndNeverSends() = Rig().use { r ->
        r.provider.enabled = false; r.drain()
        assertFalse((r.screens.last() as FeedbackScreen.Issues).available)
        r.preview(); assertFalse((r.screens.last() as FeedbackScreen.Preview).available)
        r.controller.submit(); r.drain()
        assertEquals(Failure.UNAVAILABLE, (r.screens.last() as FeedbackScreen.Notice).failure)
        assertEquals(0, r.provider.submitCount)
    }
    @Test fun nativePageControllerDrivesSubmitListDetailsAndReplyView() = Rig().use { r ->
        r.drain(); val id = r.send(); r.provider.reply="synthetic reply";r.controller.refresh(id);r.drain()
        r.controller.detail(id); r.drain()
        val detail = (r.screens.last() as FeedbackScreen.Detail).item
        assertEquals("synthetic parent description", detail.description); assertEquals("synthetic reply", detail.reply)
        assertEquals(FeedbackState.REPLIED, detail.state)
    }
    @Test fun localOnlyClearPreservesRemoteStatusDeadlineAndDoesNotWithdraw() = Rig().use { r ->
        r.drain(); val id = r.send()
        val before = (r.screens.last() as FeedbackScreen.Issues).items.single()
        r.controller.clearLocal(id); r.drain()
        val after = (r.screens.last() as FeedbackScreen.Issues).items.single()
        assertTrue(after.localCleared); assertNull(after.description); assertNull(after.reply)
        assertEquals(before.state, after.state); assertEquals(before.deleteBy, after.deleteBy)
        assertEquals(0, r.provider.withdrawCount)
        r.core.receiveReply(id, "must not repopulate local copy")
        r.controller.detail(id); r.drain(); assertNull((r.screens.last() as FeedbackScreen.Detail).item.reply)
        val reopened = FeedbackCore(FeedbackVault(r.files, r.key), r.clock, r.auth, r.provider)
        assertTrue(reopened.list().single().localCleared)
    }
    @Test fun withdrawUiUsesWholeOriginalKeyAndServerReceipt() = Rig().use { r ->
        r.drain(); val id = r.send(); r.controller.withdraw(id); r.drain()
        val item = (r.screens.last() as FeedbackScreen.Issues).items.single()
        assertEquals(FeedbackState.DELETED, item.state); assertNull(item.description); assertEquals(1, r.provider.withdrawCount)
    }
    @Test fun pauseBeforeWorkerRejectsEveryQueuedMutationAndScrubsView() = Rig().use { r ->
        r.drain(); r.controller.preview(Category.OTHER, "SYNTHETIC_SECRET", null, null)
        r.controller.pause(); r.drain()
        assertSame(FeedbackScreen.Locked, r.screens.last()); assertEquals(0, r.provider.submitCount)
    }
    @Test fun delayedUiCompletionAfterPauseCannotRestoreSensitiveSnapshot() = Rig().use { r ->
        r.work.drain(); r.ui.drain()
        r.controller.preview(Category.OTHER, "SYNTHETIC_SECRET", null, null); r.work.drain()
        r.controller.pause(); val count = r.screens.size; r.ui.drain()
        assertSame(FeedbackScreen.Locked, r.screens.last()); assertEquals(count, r.screens.size)
    }
    @Test fun oldHandleCloseCannotRevokeNewRouteOrCancelItsDraft() = Rig().use { r ->
        r.drain(); val newer = Authority(); val states = mutableListOf<FeedbackScreen>()
        val next = r.engine.open(newer, states::add)
        r.controller.close(); r.drain(); assertTrue(newer.current())
        next.preview(Category.OTHER, "new page", null, null); r.drain()
        assertEquals("new page", (states.last() as FeedbackScreen.Preview).description)
        next.close()
    }
    @Test fun editAfterPreviewInvalidatesConfirmation() = Rig().use { r ->
        r.drain(); r.preview(); r.controller.edit(); r.drain(); r.controller.submit(); r.drain()
        assertEquals(Failure.STALE, (r.screens.last() as FeedbackScreen.Notice).failure); assertEquals(0, r.provider.submitCount)
    }
    @Test fun processSystemSweepRunsWithoutAnyParentAndDeletesExpiredSource() = Rig().use { r ->
        r.drain(); r.core.record(mapOf("stage" to LogStage.PLAY, "error" to LogError.NONE, "version" to 1, "elapsedMs" to 2L, "usage" to 0L))
        r.controller.close(); r.drain(); r.clock.time += WEEK
        var done: Boolean? = null; r.engine.sweep { done = it }; r.drain(); assertEquals(true, done)
        val fresh = FeedbackCore(FeedbackVault(r.files, r.key), r.clock, Authority())
        fresh.startDraft(Category.OTHER, "new"); fresh.selectLogs(0, r.clock.time)
        assertEquals(0, fresh.preview().logs.count)
    }
    @Test fun systemTickScrubsPageAndDraftWhenParentAuthorityExpires() = Rig().use { r ->
        r.drain(); r.preview(); r.auth.close()
        r.engine.sweep(); r.drain(); r.work.drain()
        assertSame(FeedbackScreen.Locked, r.screens.last())
        val draft = FeedbackCore::class.java.getDeclaredField("draft").apply { isAccessible = true }.get(r.core)
        assertNull(draft)
    }
    @Test fun periodicSweepInvalidatesDisplayedExpiredRange() = Rig().use { r ->
        r.drain(); r.core.record(mapOf("stage" to LogStage.PLAY, "error" to LogError.NONE, "version" to 1, "elapsedMs" to 2L, "usage" to 0L))
        r.controller.preview(Category.OTHER, "synthetic", 0, r.clock.time); r.drain()
        assertEquals(1, (r.screens.last() as FeedbackScreen.Preview).logs.count)
        r.clock.time += WEEK; r.engine.sweep(); r.drain()
        assertTrue(r.screens.last() is FeedbackScreen.Editor)
        r.controller.submit(); r.drain(); assertEquals(Failure.STALE, (r.screens.last() as FeedbackScreen.Notice).failure)
    }
    @Test fun lateNetworkAdmissionAfterCloseCannotUseAnotherPageGrant() = Rig().use { r ->
        r.drain(); r.preview()
        r.provider.beforeAdmit = {
            r.controller.close()
            r.engine.open(Authority()) { }
        }
        r.controller.submit(); r.drain(); assertEquals(0, r.provider.submitCount)
    }
    @Test fun pagesOnDifferentLocalVaultsCannotReadOrClearOtherDeviceIssue() = Rig().use { a -> Rig().use { b ->
        a.drain(); b.drain(); val id = a.send()
        b.controller.detail(id); b.drain(); assertEquals(Failure.STALE, (b.screens.last() as FeedbackScreen.Notice).failure)
        b.controller.clearLocal(id); b.drain()
        a.controller.detail(id); a.drain(); assertFalse((a.screens.last() as FeedbackScreen.Detail).item.localCleared)
    } }
    @Test fun routerDoesNotBorrowNewPageAuthorityForAlreadyRunningOldWork() {
        val router = FeedbackSessionRouter(); val old = Authority(); val newer = Authority()
        router.install(old)
        router.asPage(old) {
            router.install(newer)
            assertNull(router.prepare(Operation.CLEAR_LOGS, "source-logs"))
        }
        assertTrue(newer.current())
    }
    @Test fun schemaOneLocalStoreMigratesWithoutLosingExistingRecord() = Rig().use { r ->
        val bytes = ByteArrayOutputStream()
        DataOutputStream(bytes).use { out ->
            out.writeInt(1); out.writeLong(1000); out.writeInt(0); out.writeInt(1)
            out.writeUTF("12345678-1234-1234-1234-123456789012"); out.writeUTF("OTHER"); out.writeUTF("legacy synthetic")
            out.writeInt(0); out.writeLong(1000); out.writeLong(1000); out.writeLong(1000); out.writeLong(-1)
            out.writeUTF("SUBMITTED"); out.writeUTF("")
        }
        FeedbackVault(r.files, r.key).save(bytes.toByteArray())
        val loaded = FeedbackCore(FeedbackVault(r.files, r.key), r.clock, r.auth, r.provider)
        assertEquals("legacy synthetic", loaded.list().single().description)
        assertFalse(loaded.list().single().localCleared)
    }
    @Test fun adapterCannotAcceptBooleanWithoutDecision() {
        val hasher = object : PinHasher() { override fun derive(pin: CharArray, salt: ByteArray) = ByteArray(32) { 7 } }
        val store = object : ParentStore {
            override fun read() = ParentRecord(ByteArray(16), ByteArray(32) { 7 })
            override fun write(record: ParentRecord, authorized: () -> Boolean) { check(authorized()) }
        }
        val domain = ParentDomain(store, { 1000L }, {}, binding = "synthetic-device", hasher = hasher)
        val grant = domain.verify("123456".toCharArray(), domain.enterPage())!!
        val gate = FeedbackGrantGate { _, _, _ -> true } // hostile/miswired test adapter omits decision
        val authority = ParentFeedbackAuthorizer(domain, grant, gate)
        val intent = authority.prepare(Operation.CLEAR_LOGS, "x")!!
        var called = false
        assertFalse(authority.accept(intent, Operation.CLEAR_LOGS, "x") { called = true })
        assertFalse(called)
    }
    @Test fun realParentGrantAdapterRejectsMissingGateAndRevokedGrant() {
        var now = 1000L
        val hasher = object : PinHasher() { override fun derive(pin: CharArray, salt: ByteArray) = java.security.MessageDigest.getInstance("SHA-256").digest(String(pin).toByteArray()) }
        val record = ParentRecord(ByteArray(16), hasher.derive("123456".toCharArray(), ByteArray(16)))
        val store = object : ParentStore {
            var current = record
            override fun read() = current
            override fun write(record: ParentRecord, authorized: () -> Boolean) { check(authorized()); current = record }
        }
        val domain = ParentDomain(store, { now }, {}, binding = "synthetic-device", hasher = hasher)
        val page = domain.enterPage(); val grant = domain.verify("123456".toCharArray(), page)!!
        val authority = ParentFeedbackAuthorizer(domain, grant, DenyFeedbackGrantGate)
        assertTrue(authority.current())
        val intent = authority.prepare(Operation.CLEAR_LOGS, "x")!!
        var committed = false
        assertFalse(authority.accept(intent, Operation.CLEAR_LOGS, "x") { committed = true }); assertFalse(committed)
        domain.revoke(); assertFalse(authority.current()); assertNull(authority.prepare(Operation.READ, "x"))
        val freshPage = domain.enterPage(); val fresh = domain.verify("123456".toCharArray(), freshPage)!!
        val newer = ParentFeedbackAuthorizer(domain, fresh, DenyFeedbackGrantGate)
        authority.close(); assertTrue(newer.current()) // closing old handle does not revoke newer grant
        now += ParentDomain.IDLE_MS; assertFalse(newer.current())
    }    @Test fun unscopedReplyCannotBorrowAnOtherwiseVerifiedPage() = Rig().use { r ->
        r.drain();val id=r.send()
        try { r.core.receiveReply(id,"late unscoped reply");fail("borrowed page grant") }
        catch(e:FeedbackFailure) { assertEquals(Failure.DENIED,e.reason) }
        r.controller.detail(id);r.drain();assertTrue((r.screens.last() as FeedbackScreen.Detail).item.reply.isNullOrEmpty())
    }
    @Test fun lateReadCannotBorrowNewPresentationEpoch() = Rig().use { r ->
        r.drain();val id=r.send();r.provider.reply="must not publish"
        r.provider.beforeReadReturn={ r.auth.invalidate() }
        r.controller.refresh(id);r.drain()
        assertEquals(Failure.DENIED,(r.screens.last() as FeedbackScreen.Notice).failure)
        r.controller.detail(id);r.drain();assertTrue((r.screens.last() as FeedbackScreen.Detail).item.reply.isNullOrEmpty())
    }
    @Test fun replyStagingCrossingMaterialDeadlineCannotPublishReply() = Rig().use { r ->
        r.drain();val id=r.send();r.provider.reply="must expire"
        r.onStage={r.onStage=null;r.clock.time+=WEEK}
        r.controller.refresh(id);r.drain()
        assertEquals(Failure.DENIED,(r.screens.last() as FeedbackScreen.Notice).failure)
        r.controller.showList();r.drain();assertTrue((r.screens.last() as FeedbackScreen.Issues).items.isEmpty())
    }
    @Test fun selectedLogExpiryDuringHandshakeRejectsUploadWithoutReplaying() = Rig().use { r ->
        r.drain();r.core.record(mapOf("stage" to LogStage.CONNECT,"error" to LogError.NONE,"version" to 18,"elapsedMs" to 0L,"usage" to 0L))
        r.clock.time+=WEEK-10
        r.controller.preview(Category.OTHER,"synthetic",1000,r.clock.time);r.drain()
        r.provider.beforeAdmit={r.clock.time+=10}
        r.controller.submit();r.drain()
        assertEquals(0,r.provider.submitCount)
        val item=(r.screens.last() as FeedbackScreen.Issues).items.single()
        assertEquals(FeedbackState.SEND_FAILED,item.state);assertEquals(0,item.logs.count)
    }

}
