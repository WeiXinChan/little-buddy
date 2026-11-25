package com.littlebuddy.v2.parent
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
class RevocationBoundaryTest {
 private class BlockingStore: ParentStore {
  var bytes: ByteArray? = null
  @Volatile var block=false
  val entered=CountDownLatch(1)
  val release=CountDownLatch(1)
  override fun read()=bytes?.let(ParentCodec::decode)
  override fun write(record: ParentRecord, authorized: () -> Boolean) {
   val prepared=ParentCodec.encode(record)
   if(block) { entered.countDown(); check(release.await(5,TimeUnit.SECONDS)) }
   check(authorized()) // Final authorization and commit are BOTH after the controlled IO stall.
   bytes=prepared
  }
 }
 private fun setup(): Triple<BlockingStore,ParentDomain,Pair<Long,ParentDomain.Grant>> {
  val s=BlockingStore()
  val d=ParentDomain(s,{100L},{},object:OwnerProof {override fun consume(c:OwnerChallenge)=true},"qa-only")
  var p=d.enterPage(); val c=d.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN,p)!!
  check(d.replacePin("012345".toCharArray(),c,p)); p=d.enterPage()
  return Triple(s,d,p to d.verify("012345".toCharArray(),p)!!)
 }
 @Test fun homeRevokeMustCompleteWhilePrecommitIoIsBlocked() {
  val(s,d,auth)=setup(); s.block=true
  val writeResult=AtomicReference<Boolean>(); val error=AtomicReference<Throwable>()
  val revoked=CountDownLatch(1); val invoking=CountDownLatch(1)
  val writer=Thread {try {writeResult.set(d.saveVolumeLimit(auth.second,80))}catch(t:Throwable){error.set(t)}}
  val lifecycle=Thread {invoking.countDown(); try {d.revoke()}finally {revoked.countDown()}}
  var early=false
  try {
   writer.start(); assertTrue(s.entered.await(3,TimeUnit.SECONDS))
   lifecycle.start(); assertTrue(invoking.await(1,TimeUnit.SECONDS))
   early=revoked.await(300,TimeUnit.MILLISECONDS)
  } finally {
   s.release.countDown(); writer.join(4000); if(lifecycle.state!=Thread.State.NEW) lifecycle.join(4000)
  }
  assertFalse(writer.isAlive); assertFalse(lifecycle.isAlive); assertNull(error.get())
  println("controlled_precommit: revoke_returned_within_300ms=$early write_committed=${writeResult.get()} stored_volume=${s.read()!!.volumeLimit}")
  assertFalse(d.saveVolumeLimit(auth.second,90))
  assertNull(d.verify("012345".toCharArray(),auth.first))
  assertTrue("HOME revoke waited behind precommit IO instead of invalidating immediately",early)
  assertEquals(false,writeResult.get())
 }
 @Test fun oldGrantAndEpochRejectAfterRevokeReturns() {
  val(s,d,auth)=setup(); d.revoke()
  assertFalse(d.saveVolumeLimit(auth.second,90)); assertNull(d.verify("012345".toCharArray(),auth.first))
  assertEquals(60,s.read()!!.volumeLimit)
 }
}
