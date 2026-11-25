package com.littlebuddy.v2.feedback

import java.io.IOException
import java.nio.file.Files
import javax.crypto.KeyGenerator
import org.junit.Assert.*
import org.junit.Test

class FeedbackSweepFailureTest {
    private class Queue : FeedbackQueue {
        val jobs = ArrayDeque<() -> Unit>()
        override fun post(action: () -> Unit) { jobs.addLast(action) }
        fun drain() { while (jobs.isNotEmpty()) jobs.removeFirst()() }
    }
    private class Clock(var time: Long = 1000) : FeedbackClock { override fun now() = time }
    private class Auth : FeedbackPageAuthority {
        var alive = true; private var epoch = 0
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
        var beforeFailure: (() -> Unit)? = null
        override fun read(name: String) = base.read(name)
        override fun remove(name: String) = base.remove(name)
        override fun replace(name: String, bytes: ByteArray) {
            if (fail) {
                val hook = beforeFailure; beforeFailure = null; hook?.invoke()
                throw IOException("synthetic disk failure")
            }
            base.replace(name, bytes)
        }
    }
    private class Rig : AutoCloseable {
        val dir = Files.createTempDirectory("r87-03-").toFile()
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val clock = Clock(); val work = Queue(); val ui = Queue()
        val files = FaultFiles(PrivateVaultFiles(dir)); val screens = mutableListOf<FeedbackScreen>()
        var auth = Auth(); lateinit var core: FeedbackCore
        val provider = object : FeedbackProvider {
            override fun available() = true
            override fun submit(idempotencyKey: String, payload: FeedbackPayload, admit: () -> Boolean): SubmitReceipt {
                check(admit()); return SubmitReceipt(clock.time)
            }
            override fun read(key: String, binding: String?, admit: (() -> Unit) -> Boolean): FeedbackRemote {
                check(admit {})
                return FeedbackRemote(1000L, 1000L + WEEK, FeedbackState.REPLIED, "R87_03_SYNTHETIC_REPLY")
            }
            override fun withdraw(idempotencyKey: String) = DeleteReceipt(clock.time, true)
        }
        val engine = FeedbackEngine(work, ui, { router -> FeedbackCore(FeedbackVault(files, key), clock, router, provider).also { core = it } }, { true })
        var page = engine.open(auth, screens::add)
        fun drain() { work.drain(); ui.drain() }
        fun prepare(list: Boolean = false, render: Boolean = false) {
            drain(); page.preview(Category.OTHER, "R87_03_SYNTHETIC_BODY", null, null); drain()
            page.submit(); drain(); val id = (screens.last() as FeedbackScreen.Issues).items.single().id
            page.refresh(id); drain()
            clock.time += WEEK - 1; auth = Auth(); page = engine.open(auth, screens::add); drain()
            if (list) page.showList() else page.detail(id)
            work.drain(); if (render) ui.drain()
        }
        fun failTick(atBoundary: Boolean = true) {
            if (atBoundary) clock.time++
            files.fail = true
            var success: Boolean? = null; engine.sweep { success = it }; work.drain()
            assertEquals(false, success)
        }
        fun reopened() = FeedbackCore(FeedbackVault(PrivateVaultFiles(dir), key), clock, Auth()).list()
        fun assertNoBodySince(before: Int) {
            assertFalse(screens.drop(before).any { s ->
                (s is FeedbackScreen.Detail && (s.item.description != null || s.item.reply != null)) ||
                    (s is FeedbackScreen.Issues && s.items.any { it.description != null || it.reply != null })
            })
        }
        override fun close() { page.close(); dir.deleteRecursively() }
    }
    @Test fun failedTickRetiresQueuedListAndReplyBeforeNotice() = Rig().use { r ->
        r.prepare(list = true); val before = r.screens.size
        r.failTick(); assertTrue(r.reopened().isEmpty()); r.ui.drain(); r.assertNoBodySince(before)
        assertEquals(Failure.STORAGE, (r.screens.last() as FeedbackScreen.Notice).failure)
    }
    @Test fun failedTickAlsoScrubsAlreadyDisplayedDetails() = Rig().use { r ->
        r.prepare(render = true); assertNotNull((r.screens.last() as FeedbackScreen.Detail).item.reply)
        val before = r.screens.size; r.failTick(); r.ui.drain(); r.assertNoBodySince(before)
        assertTrue(r.screens.last() is FeedbackScreen.Notice); assertTrue(r.reopened().isEmpty())
    }
    @Test fun failureBeforeBoundaryRejectsCacheWithoutClaimingDurableDeletion() = Rig().use { r ->
        r.prepare(); val before = r.screens.size
        r.failTick(atBoundary = false); r.ui.drain(); r.assertNoBodySince(before)
        assertNotNull(r.reopened().single().description) // unexpired durable record survives failed write
    }
    @Test fun retriesStayFailClosedUntilRestartThenActualVaultExpires() = Rig().use { r ->
        r.prepare(); val before = r.screens.size; r.failTick(); r.ui.drain()
        r.files.fail = false
        var retried: Boolean? = null; r.engine.sweep { retried = it }; r.drain()
        assertEquals(false, retried) // quarantined core is not silently re-enabled after failed persistence
        r.assertNoBodySince(before); assertTrue(r.reopened().isEmpty())
        val work = Queue(); val ui = Queue()
        val restarted = FeedbackEngine(work, ui, { a -> FeedbackCore(FeedbackVault(r.files, r.key), r.clock, a) })
        var recovered: Boolean? = null; restarted.sweep { recovered = it }; work.drain(); ui.drain()
        assertEquals(true, recovered); assertTrue(r.reopened().isEmpty())
    }
    @Test fun noPageFailedSweepAndRestartNeedNoPin() = Rig().use { r ->
        r.prepare(); r.page.close(); r.drain(); val before = r.screens.size
        r.failTick(); r.ui.drain(); assertEquals(before, r.screens.size); assertTrue(r.reopened().isEmpty())
    }
    @Test fun revokedAuthorityLocksInsteadOfShowingQueuedBodyOrNotice() = Rig().use { r ->
        r.prepare(); val before = r.screens.size; r.auth.close()
        r.failTick(); r.ui.drain(); r.assertNoBodySince(before)
        assertSame(FeedbackScreen.Locked, r.screens.last()); assertTrue(r.reopened().isEmpty())
    }
    @Test fun laterEditorRejectsQueuedFailureNotice() = Rig().use { r ->
        r.prepare(); val before = r.screens.size; r.failTick()
        r.page.edit(); r.work.drain(); r.ui.drain(); r.assertNoBodySince(before)
        assertTrue(r.screens.last() is FeedbackScreen.Editor)
        assertFalse(r.screens.drop(before).any { it is FeedbackScreen.Notice })
    }
    @Test fun editRequestedDuringFailedIoIsNotInvalidatedByOlderSweep() = Rig().use { r ->
        r.prepare(); val before = r.screens.size
        r.files.beforeFailure = { r.page.edit() }
        r.failTick(); r.ui.drain(); r.assertNoBodySince(before)
        assertTrue(r.screens.last() is FeedbackScreen.Editor)
        assertFalse(r.screens.drop(before).any { it is FeedbackScreen.Notice })
    }
    @Test fun newPageDuringFailedIoCannotReceiveOldFailureOrOldBody() = Rig().use { r ->
        r.prepare(); val old = r.page; val before = r.screens.size
        r.files.beforeFailure = {
            r.auth = Auth(); r.page = r.engine.open(r.auth, r.screens::add)
            r.page.edit(); old.close()
        }
        r.failTick(); r.ui.drain(); r.assertNoBodySince(before)
        assertTrue(r.auth.current()); assertTrue(r.screens.last() is FeedbackScreen.Editor)
        assertFalse(r.screens.drop(before).any { it is FeedbackScreen.Notice })
    }
    @Test fun editAfterTickEnqueuedBeforeWorkerStartsIsPreserved() = Rig().use { r ->
        r.prepare(); val before = r.screens.size; r.clock.time++; r.files.fail = true
        var success: Boolean? = null; r.engine.sweep { success = it }
        r.page.edit(); r.drain()
        assertEquals(false, success); r.assertNoBodySince(before)
        assertTrue(r.screens.last() is FeedbackScreen.Editor)
        assertFalse(r.screens.drop(before).any { it is FeedbackScreen.Notice })
    }
    @Test fun newPageAfterTickEnqueuedBeforeWorkerStartsIsPreserved() = Rig().use { r ->
        r.prepare(); val before = r.screens.size; r.clock.time++; r.files.fail = true
        var success: Boolean? = null; r.engine.sweep { success = it }
        val old = r.page; r.auth = Auth(); r.page = r.engine.open(r.auth, r.screens::add)
        r.page.edit(); old.close(); r.drain()
        assertEquals(false, success); r.assertNoBodySince(before)
        assertTrue(r.auth.current()); assertTrue(r.screens.last() is FeedbackScreen.Editor)
        assertFalse(r.screens.drop(before).any { it is FeedbackScreen.Notice })
    }
    @Test fun closeWhileFailureNoticeQueuedCannotRestorePage() = Rig().use { r ->
        r.prepare(); r.failTick(); r.page.close(); val before = r.screens.size
        r.ui.drain(); assertEquals(before, r.screens.size); assertSame(FeedbackScreen.Locked, r.screens.last())
    }
}
