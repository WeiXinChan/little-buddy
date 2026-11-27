package com.littlebuddy.v2.parent

import org.junit.Assert.*
import org.junit.Test
import org.junit.After
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class OwnerTickRegressionTest {
    @After fun disable() { PinDiagnostic.install(null) }
    private class Rig(val failWrite: Boolean = false, val consume: Boolean = true,
                      val stopAt: String? = null) {
        var time = 100L
        var stored: ParentRecord? = null
        val entered = CountDownLatch(1); val resume = CountDownLatch(1)
        val events = ConcurrentLinkedQueue<Pair<PinDiagnostic.Stage, PinDiagnostic.Reason>>()
        val work = ConcurrentLinkedQueue<() -> Unit>(); val ui = ConcurrentLinkedQueue<() -> Unit>()
        fun block(at: String) { if (at == stopAt) { entered.countDown(); check(resume.await(5, TimeUnit.SECONDS)) } }
        val domain = ParentDomain(object : ParentStore {
            override fun read() = stored
            override fun write(record: ParentRecord, authorized: () -> Boolean) {
                block("commit"); if (failWrite) throw java.io.IOException("FORBIDDEN_SECRET_PAYLOAD")
                check(authorized()); stored = record
            }
            override fun commit(record: ParentRecord, transaction: ParentCommit) {
                block("commit"); if (failWrite) throw java.io.IOException("FORBIDDEN_SECRET_PAYLOAD")
                if (!transaction.claim()) throw ParentCommitRejected()
                stored = record
            }
        }, { time }, {}, object : OwnerProof { override fun consume(challenge: OwnerChallenge) = consume },
            "test-only-binding", object : PinHasher() {
                override fun derive(pin: CharArray, salt: ByteArray): ByteArray { block("hash"); return ByteArray(32) }
            })
        val model = ParentPanelModel({ domain }, { work.offer(it) }, { ui.offer(it) }, {}, {})
        init { PinDiagnostic.install { _, _, stage, reason -> events.offer(stage to reason) } }
        fun drain() { while (work.isNotEmpty() || ui.isNotEmpty()) { work.poll()?.invoke(); ui.poll()?.invoke() } }
        fun owner() {
            model.open(); drain(); model.prepareOwner(OwnerOperation.INITIALIZE_PIN) { true }; drain()
            assertEquals(PanelMode.OWNER_PIN, model.state.mode)
        }
        fun save() { model.setOwnerPin("123456".toCharArray(), "123456".toCharArray()) }
        fun has(stage: PinDiagnostic.Stage, reason: PinDiagnostic.Reason) = events.contains(stage to reason)
        fun race(action: () -> Unit) {
            owner(); save(); val job = work.poll()!!
            val failure = java.util.concurrent.atomic.AtomicReference<Throwable?>()
            val thread = Thread { try { job() } catch (e: Throwable) { failure.set(e) } }
            thread.start()
            try { assertTrue(entered.await(5, TimeUnit.SECONDS)); action() }
            finally { resume.countDown(); thread.join(5000) }
            assertFalse(thread.isAlive); failure.get()?.let { throw AssertionError(it) }; drain()
        }
    }
    @Test fun initialPinMustSurviveTickWhileHashing() {
        val r=Rig(stopAt="hash");r.race { r.model.tick() };assertNotNull("fresh authorized save revoked by tick",r.stored)
    }
    @Test fun initialPinMustSurviveTickWhileStaging() {
        val r=Rig(stopAt="commit");r.race { r.model.tick() };assertNotNull("fresh authorized commit revoked by tick",r.stored)
    }
    @Test fun expiredSaveMustStillReject() {
        val r=Rig(stopAt="hash");r.race { r.time += 60_000; r.model.tick() };assertNull(r.stored)
    }
    @Test fun cancelledSaveMustStillReject() {
        val r=Rig(stopAt="commit");r.race { r.model.pause() };assertNull(r.stored)
    }
}
