package com.littlebuddy.v2.parent

import com.littlebuddy.v2.feedback.*
import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import javax.crypto.KeyGenerator

/** Actual model -> production binding/gate -> real authorizer/engine/core/encrypted vault.
 * Only Android widgets, trusted owner/provider/clock and scheduling are substituted. */
class ParentFeedbackCompositionTest {
    private class Store : ParentStore {
        var bytes: ByteArray? = null
        override fun read() = bytes?.let(ParentCodec::decode)
        override fun write(record: ParentRecord, authorized: () -> Boolean) {
            check(authorized()); bytes = ParentCodec.encode(record)
        }
    }
    private class Queue : FeedbackQueue {
        val jobs = ArrayDeque<() -> Unit>()
        override fun post(action: () -> Unit) { jobs.addLast(action) }
        fun drain() { while (jobs.isNotEmpty()) jobs.removeFirst()() }
    }
    private class Rig : AutoCloseable {
        var now = 1000L
        val store = Store()
        val domain = ParentDomain(store, { now }, {}, object : OwnerProof {
            override fun consume(challenge: OwnerChallenge) = true
        }, "synthetic-composition-owner")
        val parentWork = Queue(); val parentUi = Queue(); val work = Queue(); val ui = Queue()
        val dir = Files.createTempDirectory("parent-feedback-composition").toFile()
        val disk = PrivateVaultFiles(dir)
        var beforeReplace: ((String) -> Unit)? = null
        val files = object : VaultFiles {
            override fun read(name: String) = disk.read(name)
            override fun replace(name: String, bytes: ByteArray) { beforeReplace?.invoke(name); disk.replace(name, bytes) }
            override fun remove(name: String) = disk.remove(name)
        }
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        var sent = 0
        val provider = object : FeedbackProvider {
            override fun available() = true
            override fun submit(idempotencyKey: String, payload: FeedbackPayload, admit: () -> Boolean): SubmitReceipt {
                if (!admit()) throw FeedbackFailure(Failure.DENIED)
                sent++; return SubmitReceipt(now)
            }
            override fun withdraw(idempotencyKey: String) = DeleteReceipt(now, true)
        }
        val screens = mutableListOf<FeedbackScreen>()
        val engine = FeedbackEngine(work, ui, { FeedbackCore(FeedbackVault(files, key), { now }, it, provider) }, { true })
        var exits = 0
        val model = ParentPanelModel({ domain }, parentWork::post, parentUi::post, {}, { exits++ })
        class Handle(val binding: ParentFeedbackBinding, val controller: FeedbackController,
                     val exit: () -> Unit) {
            var pauses = 0; var closes = 0
            fun pause() = binding.pause { pauses++; controller.pause() }
            fun close() = binding.close { closes++; controller.close() }
        }
        val slot = ParentRouteSlot<Handle>({ it.pause() }, { it.close() })
        init {
            val page = domain.enterPage()
            check(domain.replacePin("012345".toCharArray(), domain.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN, page)!!, page))
            unlock()
        }
        fun unlock() { model.open(); parentWork.drain(); parentUi.drain(); model.verify("012345".toCharArray()); parentWork.drain(); parentUi.drain() }
        fun mount(): Handle {
            val route = model.navigate(PanelMode.FEEDBACK)!!
            return slot.show(route.revision) {
                val binding = ParentFeedbackBinding(route.domain, route.grant)
                binding.build {
                    Handle(binding, engine.open(ParentFeedbackAuthorizer(route.domain, route.grant, binding.gate), screens::add)) {
                        model.routeExit(route.revision)
                    }
                }
            }!!
        }
        fun drain() { work.drain(); ui.drain() }
        fun preview(h: Handle) { h.controller.preview(Category.OTHER, "synthetic composition material", null, null); drain() }
        fun pause() { model.pause { slot.pause() }; slot.close() }
        override fun close() { model.close(); slot.close(); work.drain(); ui.drain(); dir.deleteRecursively() }
    }
    @Test fun realGrantReachesFinalGateAndEncryptedSubmission() = Rig().use { r ->
        val h = r.mount(); r.drain(); r.preview(h)
        assertTrue(r.screens.last() is FeedbackScreen.Preview)
        h.controller.submit(); r.drain()
        assertEquals(1, r.sent); assertEquals(1, (r.screens.last() as FeedbackScreen.Issues).items.size)
        assertNotNull(r.disk.read("materials"))
    }
    @Test fun returnRotatesGrantBeforeOldCloseAndSettingsStillSaves() = Rig().use { r ->
        val h = r.mount(); r.drain(); h.exit(); r.slot.close()
        assertEquals(PanelMode.SETTINGS, r.model.state.mode)
        r.model.saveVolume(77); r.parentWork.drain(); r.parentUi.drain()
        assertEquals(77, r.store.read()!!.volumeLimit)
        h.controller.preview(Category.OTHER, "old", null, null); r.drain(); assertEquals(0, r.sent)
    }
    @Test fun oldCallbackAndCloseCannotBorrowOrRevokeNewHandle() = Rig().use { r ->
        val old = r.mount(); r.drain(); old.exit(); r.slot.close()
        val next = r.mount(); old.exit(); old.close(); r.drain(); r.preview(next)
        assertEquals(PanelMode.FEEDBACK, r.model.state.mode)
        assertTrue(r.screens.last() is FeedbackScreen.Preview)
        next.controller.submit(); r.drain(); assertEquals(1, r.sent)
    }
    @Test fun homeInvalidatesQueuedPreviewAndLateUi() = Rig().use { r ->
        val h = r.mount(); r.drain(); h.controller.preview(Category.OTHER, "old", null, null)
        r.work.drain(); r.pause(); val size = r.screens.size; r.ui.drain()
        assertEquals(size, r.screens.size); assertEquals(PanelMode.VERIFY, r.model.state.mode)
        h.controller.submit(); r.drain(); assertEquals(0, r.sent)
    }
    @Test fun focusLossRejectsQueuedSubmitAndNewHostSurvivesOldClose() = Rig().use { r ->
        val old = r.mount(); r.drain(); r.preview(old); old.controller.submit()
        r.pause(); r.unlock(); val next = r.mount(); old.close(); r.drain(); r.preview(next)
        assertEquals(0, r.sent); assertTrue(r.screens.last() is FeedbackScreen.Preview)
    }
    @Test fun idleAtEqualityRejectsFinalSubmissionWithoutPollRenewal() = Rig().use { r ->
        val h = r.mount(); r.drain(); r.preview(h); r.now += 120_000
        h.controller.submit(); r.drain(); r.model.tick(); r.slot.close()
        assertEquals(0, r.sent); assertEquals(PanelMode.VERIFY, r.model.state.mode)
    }
    @Test fun failedFactoryRevokesOnlyItsPageAndCannotRetryGrant() = Rig().use { r ->
        val route = r.model.navigate(PanelMode.FEEDBACK)!!
        val binding = ParentFeedbackBinding(route.domain, route.grant)
        assertNull(binding.build<Any> { throw IllegalStateException("synthetic factory failure") })
        assertFalse(r.domain.isAuthorized(route.grant)); assertNull(binding.build { Any() })
        r.model.tick(); assertEquals(PanelMode.VERIFY, r.model.state.mode)
        r.unlock(); val next = r.mount(); binding.close {}; r.drain(); r.preview(next)
        assertTrue(r.screens.last() is FeedbackScreen.Preview)
    }
    @Test fun handleCleanupExceptionsStillInvalidateAndReleaseSlot() = Rig().use { r ->
        val route = r.model.navigate(PanelMode.FEEDBACK)!!
        val binding = ParentFeedbackBinding(route.domain, route.grant)
        val slot = ParentRouteSlot<ParentFeedbackBinding>(
            { it.pause { throw IllegalStateException() } }, { it.close { throw IllegalStateException() } })
        slot.show(route.revision) { binding }; slot.pause(); slot.close(); slot.close()
        assertFalse(r.domain.isAuthorized(route.grant)); r.unlock()
        val next = r.mount(); binding.close {}; r.drain(); r.preview(next)
        assertTrue(r.screens.last() is FeedbackScreen.Preview)
    }
    @Test fun bindingGateRejectsForeignDomainAndNewGrantOnOldBinding() = Rig().use { r ->
        val old = r.model.navigate(PanelMode.FEEDBACK)!!
        val binding = ParentFeedbackBinding(old.domain, old.grant)
        val foreign = ParentDomain(Store(), { r.now }, {}, object : OwnerProof {
            override fun consume(challenge: OwnerChallenge) = false
        }, "untrusted-foreign-domain")
        assertFalse(binding.gate.accept(foreign, old.grant) { fail("foreign domain") })
        val next = r.domain.nextPage(old.grant)!!
        assertFalse(binding.gate.accept(r.domain, next) { fail("borrowed new Grant") })
        assertFalse(binding.gate.accept(r.domain, old.grant) { fail("old Grant") })
    }
    @Test fun closeAfterAcceptedDecisionKeepsCommittedDataButRejectsLaterWork() = Rig().use { r ->
        val h = r.mount(); r.drain(); r.preview(h); h.controller.submit(); r.drain()
        assertEquals(1, r.sent); r.pause(); h.controller.submit(); r.drain(); assertEquals(1, r.sent)
        r.unlock(); val next = r.mount(); r.drain()
        assertEquals(1, (r.screens.last() as FeedbackScreen.Issues).items.size)
        next.close()
    }
    @Test fun blockedStagingHomeReturnsWithin300msAndRejectsOldCommit() = Rig().use { r ->
        val h = r.mount(); r.drain(); r.preview(h)
        val entered = CountDownLatch(1); val release = CountDownLatch(1)
        r.beforeReplace = { name -> if (name == "staging") { entered.countDown(); check(release.await(5, TimeUnit.SECONDS)) } }
        h.controller.submit()
        val failure = AtomicReference<Throwable?>()
        val worker = Thread { try { r.work.drain() } catch (e: Throwable) { failure.set(e) } }
        worker.start()
        try {
            assertTrue(entered.await(3, TimeUnit.SECONDS))
            val start = System.nanoTime(); r.pause()
            assertTrue("HOME waited for IO", System.nanoTime() - start < 300_000_000)
        } finally { release.countDown(); worker.join(6000); r.beforeReplace = null }
        assertFalse(worker.isAlive); failure.get()?.let { throw it }; r.ui.drain()
        assertEquals(0, r.sent)
        r.unlock(); r.mount(); r.drain()
        assertTrue((r.screens.last() as FeedbackScreen.Issues).items.isEmpty())
    }
    @Test fun expiryDuringStagingRejectsAtFinalGateEvenWithoutHostTick() = Rig().use { r ->
        val h = r.mount(); r.drain(); r.preview(h)
        r.beforeReplace = { if (it == "staging") r.now += 120_000 }
        h.controller.submit(); r.drain(); r.beforeReplace = null
        assertEquals(0, r.sent); r.model.tick(); assertEquals(PanelMode.VERIFY, r.model.state.mode)
    }
    @Test fun shortDecisionExceptionRevokesOldPageWithoutTouchingLaterHost() = Rig().use { r ->
        val route = r.model.navigate(PanelMode.FEEDBACK)!!
        val binding = ParentFeedbackBinding(r.domain, route.grant)
        try { binding.gate.accept(r.domain, route.grant) { throw IllegalStateException("decision") }; fail() }
        catch (_: IllegalStateException) { }
        assertFalse(r.domain.isAuthorized(route.grant))
        r.unlock(); val next = r.mount(); binding.close {}; r.drain(); r.preview(next)
        assertTrue(r.screens.last() is FeedbackScreen.Preview)
    }

    @Test fun failedMountMustKeepRenderedCancelOperable() = Rig().use { r ->
        val h = r.mount(); r.drain(); val route = r.model.currentRoute()!!
        r.slot.mount(route.revision, { fail("existing handle must be reused"); h },
            { throw IllegalStateException("synthetic Android presentation failure") }, {
                r.model.routeFailed(route.revision) { r.slot.close(route.revision) }
            })
        // QA's original recovery assertions, now reached through the actual host's shared boundary.
        assertEquals(PanelMode.VERIFY,r.model.state.mode)
        assertEquals(ParentDomain.State.LOCKED,r.domain.state())
        val accepted=r.model.userAction(r.model.viewToken){r.model.exit()}
        assertTrue("visible locked-page Cancel is rejected because mount recovery left active=false",accepted)
        assertEquals(1, r.exits); assertEquals(1, h.closes)
        assertFalse(r.domain.isAuthorized(route.grant))
        r.unlock(); val next = r.mount(); h.exit(); h.close(); r.drain(); r.preview(next)
        assertTrue(r.screens.last() is FeedbackScreen.Preview)
    }
    @Test fun failedFactoryUsesSameOperableLockedRecovery() = Rig().use { r ->
        val route = r.model.navigate(PanelMode.FEEDBACK)!!
        val binding = ParentFeedbackBinding(r.domain, route.grant)
        r.slot.mount(route.revision, { binding.build<Rig.Handle> { throw IllegalStateException() } },
            { fail("failed factory must not mount") }, {
                r.model.routeFailed(route.revision) { r.slot.close(route.revision) }
            })
        assertEquals(PanelMode.VERIFY, r.model.state.mode)
        assertTrue(r.model.userAction(r.model.viewToken) { r.model.exit() }); assertEquals(1, r.exits)
        assertFalse(r.domain.isAuthorized(route.grant))
    }
    @Test fun mountRecoveryRequiresFreshVerificationAndRejectsOldButtonsAndCallbacks() = Rig().use { r ->
        val h = r.mount(); r.drain(); val route = r.model.currentRoute()!!; val oldButton = r.model.viewToken
        r.model.routeFailed(route.revision) { r.slot.close(route.revision) }
        assertFalse(r.model.userAction(oldButton) { fail("obsolete view") })
        h.exit(); r.model.saveVolume(89); r.parentWork.drain(); r.parentUi.drain()
        assertEquals(60, r.store.read()!!.volumeLimit); assertEquals(PanelMode.VERIFY, r.model.state.mode)
        assertTrue(r.model.userAction(r.model.viewToken) { r.model.verify("012345".toCharArray()) })
        r.parentWork.drain(); r.parentUi.drain(); assertEquals(PanelMode.SETTINGS, r.model.state.mode)
        r.model.saveVolume(81); r.parentWork.drain(); r.parentUi.drain()
        assertEquals(81, r.store.read()!!.volumeLimit); assertEquals(1, h.closes)
    }
    @Test fun cleanupExceptionCannotLeaveForegroundRecoveryInactive() = Rig().use { r ->
        val h = r.mount(); val route = r.model.currentRoute()!!
        r.model.routeFailed(route.revision) { r.slot.close(route.revision); throw IllegalStateException() }
        assertEquals(1, h.closes)
        assertTrue(r.model.userAction(r.model.viewToken) { r.model.exit() }); assertEquals(1, r.exits)
        assertFalse(r.domain.isAuthorized(route.grant))
    }
    @Test fun homeDuringRecoveryCleanupNeverReactivatesBackground() = Rig().use { r ->
        r.mount(); val route = r.model.currentRoute()!!
        r.model.routeFailed(route.revision) { r.slot.close(route.revision); r.model.pause() }
        assertFalse(r.model.userAction(r.model.viewToken) { fail("background reactivated") })
        val pin = "012345".toCharArray(); r.model.verify(pin)
        assertTrue(pin.all { it == '\u0000' }); assertEquals(0, r.exits)
    }
    @Test fun lateMountFailureCannotCloseOrLockReplacementRoute() = Rig().use { r ->
        val old = r.mount(); val ticket = r.model.currentRoute()!!.revision; old.exit(); r.slot.close()
        val next = r.mount()
        r.model.routeFailed(ticket) { r.slot.close(ticket) }; r.drain(); r.preview(next)
        assertEquals(0, next.closes); assertEquals(PanelMode.FEEDBACK, r.model.state.mode)
        assertTrue(r.screens.last() is FeedbackScreen.Preview)
    }
    @Test fun cleanupAfterMountFailureCannotRevokeDifferentHostsNewGrant() = Rig().use { r ->
        r.mount(); val route = r.model.currentRoute()!!
        var next: ParentDomain.Grant? = null
        r.model.routeFailed(route.revision) {
            val page = r.domain.enterPage(); next = r.domain.verify("012345".toCharArray(), page)!!
            r.slot.close(route.revision)
        }
        assertTrue(r.domain.isAuthorized(next!!))
        assertFalse(r.domain.isAuthorized(route.grant))
        assertTrue(r.model.userAction(r.model.viewToken) { r.model.exit() })
        assertTrue(r.domain.isAuthorized(next!!))
    }

}
