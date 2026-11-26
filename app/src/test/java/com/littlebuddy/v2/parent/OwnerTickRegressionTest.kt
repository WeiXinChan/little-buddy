package com.littlebuddy.v2.parent

import org.junit.Assert.*
import org.junit.Test
import org.junit.After
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class OwnerTickRegressionTest {
    private class Rig(val failWrite: Boolean = false, val consume: Boolean = true,
                      val stopAt: String? = null, val owned: Boolean = false) {
        var time = 100L
        var stored: ParentRecord? = if (owned) ParentRecord(ByteArray(16), ByteArray(32)) else null
        val entered = CountDownLatch(1); val resume = CountDownLatch(1)
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
        }, { time }, {}, object : OwnerProof { override fun consume(challenge: OwnerChallenge): Boolean { block("consume"); return consume } },
            "test-only-binding", object : PinHasher() {
                override fun derive(pin: CharArray, salt: ByteArray): ByteArray { block("hash"); return ByteArray(32) }
            })
        val model = ParentPanelModel({ domain }, { work.offer(it) }, { ui.offer(it) }, {}, {})
        fun drain() { while (work.isNotEmpty() || ui.isNotEmpty()) { work.poll()?.invoke(); ui.poll()?.invoke() } }
        fun owner() {
            model.open(); drain(); model.prepareOwner(if (owned) OwnerOperation.RESET_PIN else OwnerOperation.INITIALIZE_PIN) { true }; drain()
            assertEquals(PanelMode.OWNER_PIN, model.state.mode)
        }
        fun save() { model.setOwnerPin("123456".toCharArray(), "123456".toCharArray()) }
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
    @Test fun tickBeforeWorkerStartsKeepsFreshChallenge() {
        val r=Rig();r.owner();r.save();r.model.tick();r.drain();assertNotNull(r.stored)
    }
    @Test fun expiryBeforeWorkerStartsStillRejects() {
        val r=Rig();r.owner();r.save();r.time+=60_000;r.model.tick();r.drain();assertNull(r.stored)
    }
    @Test fun pauseBeforeWorkerStartsStillRejects() {
        val r=Rig();r.owner();r.save();r.model.pause();r.drain();assertNull(r.stored)
    }
    @Test fun committedRecordSurvivesTickBeforeUiCallback() {
        val r=Rig();r.owner();r.save();r.work.poll()!!();r.model.tick();r.drain()
        assertNotNull(r.stored);assertEquals(ParentDomain.State.LOCKED,r.domain.state())
    }

    @Test fun consumeFailureAfterTicksNeverDerivesOrCommits() {
        val r=Rig(consume=false,stopAt="consume");r.race {
            repeat(3) { r.model.tick(); assertEquals(PanelMode.OWNER_PIN,r.model.state.mode) }
        };assertNull(r.stored);assertEquals(ParentDomain.State.UNOWNED,r.domain.state())
    }
    @Test fun exactExpiryDuringHashLocksBeforeWorkerResumes() {
        val r=Rig(stopAt="hash");r.race {
            r.time+=59_999;r.model.tick();assertEquals(PanelMode.OWNER_PIN,r.model.state.mode)
            r.time++;r.model.tick();assertEquals(PanelMode.UNAVAILABLE,r.model.state.mode)
            assertFalse(r.model.state.busy)
        };assertNull(r.stored)
    }
    @Test fun pageReplacementDuringHashCannotBorrowNewPage() {
        val r=Rig(stopAt="hash");r.race {
            r.domain.enterPage();r.model.tick();assertEquals(PanelMode.UNAVAILABLE,r.model.state.mode)
        };assertNull(r.stored)
    }
    @Test fun writeFailureAfterFreshTicksStaysQuarantined() {
        val r=Rig(failWrite=true,stopAt="commit");r.race { r.model.tick() }
        assertNull(r.stored);assertEquals(ParentDomain.State.QUARANTINED,r.domain.state())
    }
    @Test fun recoverySaveSurvivesTicksWithoutRestoringGrant() {
        val r=Rig(stopAt="hash",owned=true);val before=r.stored
        r.race { repeat(3) { r.model.tick();assertEquals(PanelMode.OWNER_PIN,r.model.state.mode) } }
        assertNotSame(before,r.stored);assertEquals(ParentDomain.State.LOCKED,r.domain.state())
    }
    @Test fun recoveryFailureKeepsPriorRecordAndNeverBecomesUnowned() {
        val r=Rig(failWrite=true,stopAt="commit",owned=true);val before=r.stored
        r.race { r.model.tick() };assertSame(before,r.stored)
        assertEquals(ParentDomain.State.QUARANTINED,r.domain.state())
    }

}
