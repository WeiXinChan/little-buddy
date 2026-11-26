package com.littlebuddy.v2.parent

import org.junit.Assert.*
import org.junit.Test
import org.junit.After
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class PinDiagnosticTest {
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
    @Test fun successIsDistinct() {
        val r = Rig(); r.owner(); r.save(); r.drain(); assertNotNull(r.stored)
        assertTrue(r.has(PinDiagnostic.Stage.CONSUME, PinDiagnostic.Reason.SUCCESS))
        assertTrue(r.has(PinDiagnostic.Stage.COMMIT, PinDiagnostic.Reason.SUCCESS))
    }
    @Test fun consumedChallengePlusRealTickDuringHasherReproducesUnowned() {
        val r = Rig(stopAt="hash"); r.race { r.model.tick() }
        assertNull(r.stored); assertEquals(ParentDomain.State.UNOWNED, r.domain.state())
        assertTrue(r.has(PinDiagnostic.Stage.TICK, PinDiagnostic.Reason.SAVE_IN_PROGRESS))
        assertTrue(r.has(PinDiagnostic.Stage.TICK, PinDiagnostic.Reason.TICK_OWNER_INVALID))
        assertTrue(r.has(PinDiagnostic.Stage.CONSUME, PinDiagnostic.Reason.SUCCESS))
        assertTrue(r.has(PinDiagnostic.Stage.COMMIT, PinDiagnostic.Reason.REJECTED))
    }
    @Test fun consumedChallengePlusRealTickDuringCommitReproducesUnowned() {
        val r = Rig(stopAt="commit"); r.race { r.model.tick() }
        assertNull(r.stored); assertTrue(r.has(PinDiagnostic.Stage.COMMIT, PinDiagnostic.Reason.REJECTED))
    }
    @Test fun genuineExpiryStillRejects() {
        val r = Rig(stopAt="hash"); r.race { r.time += 120_000; r.model.tick() }; assertNull(r.stored)
        assertTrue(r.has(PinDiagnostic.Stage.PAGE, PinDiagnostic.Reason.EXPIRED))
    }
    @Test fun focusCancellationStillRejects() {
        val r = Rig(stopAt="hash"); r.race { r.model.pause() }; assertNull(r.stored)
        assertTrue(r.has(PinDiagnostic.Stage.PAGE, PinDiagnostic.Reason.CANCEL))
    }
    @Test fun consumeRejectionHasNoDeriveOrWrite() {
        val r=Rig(consume=false); r.owner(); r.save(); r.drain(); assertNull(r.stored)
        assertTrue(r.has(PinDiagnostic.Stage.CONSUME,PinDiagnostic.Reason.REJECTED))
        assertFalse(r.has(PinDiagnostic.Stage.DERIVE,PinDiagnostic.Reason.BEGIN))
    }
    @Test fun writeFailureIsWhitelistedAndQuarantined() {
        val r=Rig(failWrite=true);r.owner();r.save();r.drain()
        assertEquals(ParentDomain.State.QUARANTINED,r.domain.state())
        assertTrue(r.has(PinDiagnostic.Stage.COMMIT,PinDiagnostic.Reason.IO_ERROR))
        assertFalse(r.events.toString().contains("FORBIDDEN_SECRET_PAYLOAD"))
    }
    @Test fun throwingSinkCannotChangeSuccess() {
        val r=Rig();r.owner();PinDiagnostic.install { _,_,_,_ -> throw IllegalStateException("SECRET") }
        r.save();r.drain();assertNotNull(r.stored)
    }
}
