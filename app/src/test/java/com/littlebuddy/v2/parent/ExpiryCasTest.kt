package com.littlebuddy.v2.parent
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference
class ExpiryCasTest {
 private class Clock {
  val t=AtomicLong(100L)
  @Volatile var armed=false
  var reads=0
  var afterLastRead: () -> Unit = {}
  fun now():Long {
   val captured=t.get()
   if(armed && ++reads==2) afterLastRead() // preemption after final deadline sample, before epoch CAS
   return captured
  }
 }
 private class Store(val clock:Clock):ParentStore {
  var bytes:ByteArray?=null
  var armFinal=false
  override fun read()=bytes?.let(ParentCodec::decode)
  override fun write(r:ParentRecord,a:()->Boolean) {check(a());bytes=ParentCodec.encode(r)}
  override fun commit(r:ParentRecord,tx:ParentCommit) {
   if(armFinal) clock.armed=true
   tx.claim()
   bytes=ParentCodec.encode(r)
  }
 }
 private fun setup(c:Clock,s:Store):Pair<ParentDomain,ParentDomain.Grant> {
  val d=ParentDomain(s,c::now,{},object:OwnerProof{override fun consume(challenge:OwnerChallenge)=true},"qa")
  val p=d.enterPage(); check(d.replacePin("012345".toCharArray(),d.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN,p)!!,p))
  return d to d.verify("012345".toCharArray(),d.enterPage())!!
 }
 @Test fun expiresAfterFinalClockSampleBeforeClaimMustNotCommit() {
  val c=Clock();val s=Store(c);val(d,g)=setup(c,s)
  val sampled=CountDownLatch(1);val release=CountDownLatch(1)
  c.t.set(120099L);s.armFinal=true
  c.afterLastRead={sampled.countDown();check(release.await(5,TimeUnit.SECONDS))}
  val result=AtomicReference<Boolean>();val error=AtomicReference<Throwable>()
  val writer=Thread{try{result.set(d.saveVolumeLimit(g,80))}catch(t:Throwable){error.set(t)}}
  try {writer.start();assertTrue(sampled.await(3,TimeUnit.SECONDS));c.t.set(120100L)}
  finally {release.countDown();writer.join(4000)}
  assertFalse(writer.isAlive);assertNull(error.get())
  println("deadline_before_CAS: expired_at=120100 committed=${result.get()} volume=${s.read()!!.volumeLimit}")
  assertEquals("expiry won before documented claim CAS",false,result.get())
  assertEquals(60,s.read()!!.volumeLimit)
 }
 @Test fun revokeAfterFinalClockSampleBeforeClaimRejects() {
  val c=Clock();val s=Store(c);val(d,g)=setup(c,s)
  c.t.set(120099L);s.armFinal=true;c.afterLastRead={d.revoke()}
  assertFalse(d.saveVolumeLimit(g,80));assertEquals(60,s.read()!!.volumeLimit)
 }
}
