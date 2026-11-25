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
class IndependentCompositionTest {
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
        var beforeAdmission: (() -> Unit)? = null
        var sent = 0
        val provider = object : FeedbackProvider {
            override fun available() = true
            override fun submit(idempotencyKey: String, payload: FeedbackPayload, admit: () -> Boolean): SubmitReceipt {
                beforeAdmission?.invoke()
                if (!admit()) throw FeedbackFailure(Failure.DENIED)
                sent++; return SubmitReceipt(now)
            }
            override fun withdraw(idempotencyKey: String) = DeleteReceipt(now, true)
        }
        val screens = mutableListOf<FeedbackScreen>()
        val engine = FeedbackEngine(work, ui, { FeedbackCore(FeedbackVault(files, key), { now }, it, provider) }, { true })
        val model = ParentPanelModel({ domain }, parentWork::post, parentUi::post, {}, {})
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

    @Test fun providerAdmissionRechecksGrantAfterDurableLocalCommit() = Rig().use { r ->
        val h=r.mount();r.drain();r.preview(h)
        var reached=false
        r.beforeAdmission={reached=true;assertNotNull(r.disk.read("materials"));r.now+=120_000}
        h.controller.submit();r.drain()
        assertTrue(reached);assertEquals(0,r.sent)
        r.model.tick();assertEquals(PanelMode.VERIFY,r.model.state.mode)
    }
    @Test fun returnDuringBlockedStagingRejectsOldCommitAndPreservesSettingsGrant() = Rig().use { r ->
        val h=r.mount();r.drain();r.preview(h)
        val entered=CountDownLatch(1);val release=CountDownLatch(1)
        r.beforeReplace={if(it=="staging"){entered.countDown();check(release.await(5,TimeUnit.SECONDS))}}
        h.controller.submit();val error=AtomicReference<Throwable?>()
        val worker=Thread{try{r.work.drain()}catch(t:Throwable){error.set(t)}};worker.start()
        try {
            assertTrue(entered.await(3,TimeUnit.SECONDS))
            val start=System.nanoTime();h.exit();r.slot.close()
            assertTrue("return waited for staging IO",System.nanoTime()-start<300_000_000)
            assertEquals(PanelMode.SETTINGS,r.model.state.mode)
        } finally {release.countDown();worker.join(6000);r.beforeReplace=null}
        assertFalse(worker.isAlive);error.get()?.let{throw it};r.ui.drain()
        assertEquals(0,r.sent)
        r.model.saveVolume(83);r.parentWork.drain();r.parentUi.drain()
        assertEquals(83,r.store.read()!!.volumeLimit)
    }
    @Test fun failedFactoryDoesNotRevokeLaterPageCreatedBeforeException() = Rig().use { r ->
        val route=r.model.navigate(PanelMode.FEEDBACK)!!
        val binding=ParentFeedbackBinding(r.domain,route.grant)
        var next:ParentDomain.Grant?=null
        assertNull(binding.build<Any>{next=r.domain.nextPage(route.grant);error("factory")})
        assertNotNull(next);assertTrue(r.domain.isAuthorized(next!!))
        binding.close{error("cleanup")};assertTrue(r.domain.isAuthorized(next!!))
    }
}
