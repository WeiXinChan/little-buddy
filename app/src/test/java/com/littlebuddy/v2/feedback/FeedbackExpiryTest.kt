package com.littlebuddy.v2.feedback

import java.nio.file.Files
import javax.crypto.KeyGenerator
import org.junit.Assert.*
import org.junit.Test

class FeedbackExpiryTest {
    private class Queue : FeedbackQueue {
        val jobs = ArrayDeque<() -> Unit>()
        override fun post(action: () -> Unit) { jobs.addLast(action) }
        fun drain() { while (jobs.isNotEmpty()) jobs.removeFirst()() }
    }
    private class Clock(var time: Long = 1000L) : FeedbackClock { override fun now() = time }
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
    private class Rig : AutoCloseable {
        val dir = Files.createTempDirectory("r87-02-").toFile()
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val clock = Clock(); val work = Queue(); val ui = Queue()
        val screens = mutableListOf<FeedbackScreen>()
        var auth = Auth(); lateinit var core: FeedbackCore
        val provider = object : FeedbackProvider {
            override fun available() = true
            override fun submit(idempotencyKey: String, payload: FeedbackPayload, admit: () -> Boolean): SubmitReceipt {
                check(admit()); return SubmitReceipt(clock.time)
            }
            override fun withdraw(idempotencyKey: String) = DeleteReceipt(clock.time, false)
        }
        val engine = FeedbackEngine(work, ui, { router -> FeedbackCore(FeedbackVault(PrivateVaultFiles(dir), key), clock, router, provider).also { core = it } }, { true })
        var page = engine.open(auth, screens::add)
        fun drain() { work.drain(); ui.drain() }
        fun send(logs: Boolean = false): String {
            drain()
            page.preview(Category.OTHER, "R87_02_SYNTHETIC_DESCRIPTION", if (logs) 1000 else null, if (logs) 1000 else null)
            drain(); page.submit(); drain()
            return (screens.last() as FeedbackScreen.Issues).items.single().id
        }
        fun fresh(id: String) {
            auth = Auth(); page = engine.open(auth, screens::add); drain(); page.detail(id); drain()
        }
        fun tick() { var success: Boolean? = null; engine.sweep { success = it }; drain(); assertEquals(true, success) }
        fun durable() = FeedbackCore(FeedbackVault(PrivateVaultFiles(dir), key), clock, Auth()).list()
        fun noBody() {
            val last = screens.last()
            assertFalse(last is FeedbackScreen.Detail && (last.item.description != null || last.item.reply != null))
            assertFalse(last is FeedbackScreen.Issues && last.items.any { it.description != null || it.reply != null })
        }
        override fun close() { page.close(); dir.deleteRecursively() }
    }
    @Test fun exactBoundaryWithFreshAuthorityRefreshesReplyAndRepeatedTicks() = Rig().use { r ->
        val id = r.send(); r.core.receiveReply(id, "R87_02_SYNTHETIC_REPLY")
        r.clock.time += WEEK - 1; r.fresh(id)
        assertNotNull((r.screens.last() as FeedbackScreen.Detail).item.reply)
        r.tick(); assertNotNull((r.screens.last() as FeedbackScreen.Detail).item.description)
        r.clock.time++; r.tick(); r.noBody(); assertTrue(r.auth.current()); assertTrue(r.durable().isEmpty())
        r.tick(); r.noBody(); assertTrue(r.durable().isEmpty())
    }
    @Test fun listCacheAlsoExpiresWithoutNavigation() = Rig().use { r ->
        val id = r.send(); r.clock.time += WEEK - 1; r.fresh(id)
        r.page.showList(); r.drain(); assertEquals(1, (r.screens.last() as FeedbackScreen.Issues).items.size)
        r.clock.time++; r.tick()
        assertTrue((r.screens.last() as FeedbackScreen.Issues).items.isEmpty()); assertTrue(r.durable().isEmpty())
    }
    @Test fun unrenderedDetailCannotRestoreAfterSuccessfulTick() = Rig().use { r ->
        val id = r.send(); r.clock.time += WEEK - 1; r.fresh(id)
        r.page.detail(id); r.work.drain() // UI delivery intentionally blocked
        val before = r.screens.size
        r.clock.time++; var swept = false; r.engine.sweep { swept = it }; r.work.drain()
        assertTrue(swept); assertTrue(r.durable().isEmpty())
        r.ui.drain(); r.noBody()
        assertFalse(r.screens.drop(before).any { it is FeedbackScreen.Detail && it.item.description != null })
    }
    @Test fun unrenderedListCannotRestoreAfterSuccessfulTick() = Rig().use { r ->
        val id = r.send(); r.clock.time += WEEK - 1; r.fresh(id)
        r.page.showList(); r.work.drain(); val before = r.screens.size
        r.clock.time++; r.engine.sweep(); r.work.drain(); r.ui.drain()
        assertTrue((r.screens.last() as FeedbackScreen.Issues).items.isEmpty())
        assertFalse(r.screens.drop(before).any { it is FeedbackScreen.Issues && it.items.any { item -> item.description != null } })
    }
    @Test fun noParentPageStillExpiresRealVault() = Rig().use { r ->
        r.send(); r.page.close(); r.drain(); r.clock.time += WEEK
        r.tick(); assertTrue(r.durable().isEmpty()); r.noBody()
    }
    @Test fun revokedAuthorityLocksDetailsAndStillExpiresRealVault() = Rig().use { r ->
        val id = r.send(); r.clock.time += WEEK - 1; r.fresh(id)
        r.auth.close(); r.clock.time++; r.tick()
        assertSame(FeedbackScreen.Locked, r.screens.last()); assertTrue(r.durable().isEmpty())
    }
    @Test fun pendingRefreshCannotOverwriteLaterEditor() = Rig().use { r ->
        val id = r.send(); r.clock.time += WEEK - 1; r.fresh(id)
        r.clock.time++; r.engine.sweep(); r.work.drain() // refreshed result queued to UI
        r.page.edit(); r.work.drain(); r.ui.drain()
        assertTrue(r.screens.last() is FeedbackScreen.Editor); assertTrue(r.durable().isEmpty())
    }
    @Test fun queuedEditBeforeSweepIsNotClaimedByOldDetailRefresh() = Rig().use { r ->
        val id = r.send(); r.clock.time += WEEK - 1; r.fresh(id)
        r.clock.time++; r.engine.sweep(); r.page.edit(); r.drain()
        assertTrue(r.screens.last() is FeedbackScreen.Editor); assertTrue(r.durable().isEmpty())
    }
    @Test fun pageSwitchCannotRestoreOldDetailsOrRevokeNewPage() = Rig().use { r ->
        val id = r.send(); r.clock.time += WEEK - 1; r.fresh(id)
        val old = r.page; r.clock.time++; r.engine.sweep(); r.work.drain()
        r.auth = Auth(); r.page = r.engine.open(r.auth, r.screens::add)
        old.close(); r.drain(); r.page.edit(); r.drain()
        assertTrue(r.auth.current()); assertTrue(r.screens.last() is FeedbackScreen.Editor); assertTrue(r.durable().isEmpty())
    }
    @Test fun selectedLogRangeExpiresBeforeDescriptionAndRefreshesDetail() = Rig().use { r ->
        r.drain(); r.core.record(mapOf("stage" to LogStage.CONNECT, "error" to LogError.NONE,
            "version" to 1, "elapsedMs" to 1L, "usage" to 1L))
        r.clock.time += 100; val id = r.send(true)
        r.clock.time = 1000 + WEEK - 1; r.fresh(id)
        assertEquals(1, (r.screens.last() as FeedbackScreen.Detail).item.logs.count)
        r.clock.time++; r.tick()
        val detail = (r.screens.last() as FeedbackScreen.Detail).item
        assertEquals(0, detail.logs.count); assertNotNull(detail.description)
        assertEquals(0, r.durable().single().logs.bytes)
    }
    @Test fun earlierWithdrawalDeadlineAndLocalClearNeverRestoreBody() = Rig().use { r ->
        val id = r.send(); r.page.clearLocal(id); r.drain(); r.page.detail(id); r.drain()
        assertTrue((r.screens.last() as FeedbackScreen.Detail).item.localCleared)
        r.page.withdraw(id); r.drain(); val deadline = 1000 + DAY
        r.clock.time = deadline - 1; r.fresh(id); r.noBody()
        assertEquals(deadline, (r.screens.last() as FeedbackScreen.Detail).item.deleteBy)
        r.clock.time++; r.tick(); r.noBody(); r.tick(); r.noBody()
        val material = r.durable().single(); assertNull(material.description); assertNull(material.reply)
        assertEquals(deadline, material.deleteBy)
    }
}
