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
class RecoveryBoundaryTest {
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

    @Test fun openDuringFailureCleanupKeepsNewForegroundRevision() = Rig().use { r ->
        val old=r.mount();val route=r.model.currentRoute()!!
        r.model.routeFailed(route.revision){r.slot.close(route.revision);r.model.open()}
        r.parentWork.drain();r.parentUi.drain()
        assertEquals(PanelMode.VERIFY,r.model.state.mode)
        assertTrue(r.model.userAction(r.model.viewToken){r.model.verify("012345".toCharArray())})
        r.parentWork.drain();r.parentUi.drain();assertEquals(PanelMode.SETTINGS,r.model.state.mode)
        old.close();r.model.saveVolume(86);r.parentWork.drain();r.parentUi.drain()
        assertEquals(86,r.store.read()!!.volumeLimit)
    }
    @Test fun failureRevokesBeforeReleaseAndCancelWorks() = Rig().use { r ->
        val old=r.mount();val route=r.model.currentRoute()!!
        r.model.routeFailed(route.revision){
            r.slot.close(route.revision)
            assertFalse(r.domain.isAuthorized(route.grant))
        }
        assertFalse(r.model.currentRoute()!=null)
        assertTrue(r.model.userAction(r.model.viewToken){r.model.exit()})
        old.close()
    }
    @Test fun factoryReentryMustNotOverwriteNewHandleOrLoseRelease() {
        data class Handle(val id:Int)
        val closed=mutableListOf<Int>();val shown=mutableListOf<Int>()
        val slot=ParentRouteSlot<Handle>({}, {closed.add(it.id)})
        slot.mount(1,{
            slot.mount(2,{Handle(2)},{shown.add(it.id)},{fail("new mount failed")})
            Handle(1)
        },{shown.add(it.id)},{fail("old mount failure")})
        assertEquals(listOf(2),shown)
        slot.close(2)
        assertTrue("new route handle lost during reentrant factory: closed="+closed,2 in closed)
        assertTrue("retired factory handle leaked: closed="+closed,1 in closed)
    }
}
