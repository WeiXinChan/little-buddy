package com.littlebuddy.v2.parent

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class ConnectionSaveTest {
    private class Rig(val at:String="commit",val consume:Boolean=true,val fail:Boolean=false) {
        var now=0L;var record=ParentRecord(ByteArray(16),ByteArray(32))
        val entered=CountDownLatch(1);val resume=CountDownLatch(1)
        var block=false
        fun waitAt(point:String){if(block&&at==point){entered.countDown();check(resume.await(5,TimeUnit.SECONDS))}}
        val domain=ParentDomain(object:ParentStore{
            override fun read()=record
            override fun write(next:ParentRecord,authorized:()->Boolean){check(authorized());record=next}
            override fun commit(next:ParentRecord,transaction:ParentCommit){
                waitAt("commit");if(fail&&block)error("synthetic disk failure")
                if(!transaction.claim())throw ParentCommitRejected();record=next
            }
        },{now},{},object:OwnerProof{override fun consume(challenge:OwnerChallenge):Boolean{waitAt("consume");return consume}},"synthetic-binding",
        object:PinHasher(){override fun derive(pin:CharArray,salt:ByteArray)=ByteArray(32)})
        val work=ConcurrentLinkedQueue<()->Unit>();val ui=ConcurrentLinkedQueue<()->Unit>()
        val model=ParentPanelModel({domain},{work.add(it)},{ui.add(it)},{},{})
        fun drain(){while(work.isNotEmpty()||ui.isNotEmpty()){work.poll()?.invoke();ui.poll()?.invoke()}}
        fun ready(){model.open();drain();model.verify("123456".toCharArray());drain()
            model.prepareOwner(OwnerOperation.PROVISION_ENDPOINT){true};drain();assertEquals(PanelMode.CONNECTION,model.state.mode)}
        fun race(action:()->Unit){
            ready();block=true;model.importConnection(ADDRESS,"a".repeat(32).toCharArray(),USER)
            val job=work.poll()!!;val error=java.util.concurrent.atomic.AtomicReference<Throwable?>()
            val t=Thread{try{job()}catch(e:Throwable){error.set(e)}};t.start()
            try{assertTrue(entered.await(5,TimeUnit.SECONDS));action()}finally{resume.countDown();t.join(5000)}
            assertFalse(t.isAlive);error.get()?.let{throw AssertionError(it)};drain()
        }
    }
    @Test fun consumedConnectionSurvivesRealTickDuringCommit(){val r=Rig();r.race{r.model.tick()};assertNotNull("fresh connection revoked by tick",r.record.connection)}
    @Test fun consumedConnectionSurvivesRealTickDuringOwnerConsume(){val r=Rig(at="consume");r.race{r.model.tick()};assertNotNull("fresh consume revoked by tick",r.record.connection)}
    @Test fun exactExpiryLocksBeforeBlockedIoReturns(){val r=Rig();r.race{r.now=59999;r.model.tick();assertEquals(PanelMode.CONNECTION,r.model.state.mode);r.now++;r.model.tick();assertEquals(PanelMode.VERIFY,r.model.state.mode)};assertNull(r.record.connection)}
    @Test fun pauseStillRejectsAndWipesCallerInput(){val r=Rig();r.race{r.model.pause()};assertNull(r.record.connection)}
    @Test fun consumeFalseCannotPublish(){val r=Rig(at="consume",consume=false);r.race{r.model.tick()};assertNull(r.record.connection)}
    @Test fun storageFailureQuarantines(){val r=Rig(fail=true);r.race{r.model.tick()};assertNull(r.record.connection);assertEquals(ParentDomain.State.QUARANTINED,r.domain.state())}
    @Test fun replacementPageCannotBorrowOldCommit(){val r=Rig();r.race{r.domain.enterPage();r.model.tick()};assertNull(r.record.connection)}
    @Test fun successStillLocksAndRequiresExplicitPin(){val r=Rig();r.ready();r.model.importConnection(ADDRESS,"a".repeat(32).toCharArray(),USER);r.drain();assertNotNull(r.record.connection);assertEquals(ParentDomain.State.LOCKED,r.domain.state());assertEquals(PanelNotice.CONNECTION_SAVED,r.model.state.notice)}
    companion object { const val ADDRESS="wss://127.0.0.1:19483/v2/voice";const val USER="v2-device-oppo" }
}
