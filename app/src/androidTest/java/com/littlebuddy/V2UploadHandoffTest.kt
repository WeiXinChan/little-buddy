package com.littlebuddy
import android.os.Handler
import android.os.HandlerThread
import androidx.test.platform.app.InstrumentationRegistry
import com.littlebuddy.v2.*
import org.junit.Test
import org.junit.Assert.*
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
class V2UploadHandoffTest {
 private fun batch(n:Int)=List((n+319)/320){i->ShortArray(minOf(320,n-i*320)){j->(i*320+j).toShort()}}
 @Test fun actualPausedHandlerPreserves8129SampleWakeHandoffOnce(){
  val thread=HandlerThread("handoff-owner").apply{start()};val owner=Handler(thread.looper)
  val entered=CountDownLatch(1);val release=CountDownLatch(1);val done=CountDownLatch(1);val posts=AtomicInteger();val received=mutableListOf<Short>()
  owner.post{entered.countDown();release.await(5,TimeUnit.SECONDS)}
  val q=CaptureUploads({posts.incrementAndGet();owner.post(it)},{true},{d,_,_->received.addAll(d.toList());if(received.size==8129)done.countDown()},{throw it})
  try {
   assertTrue(entered.await(2,TimeUnit.SECONDS));assertTrue(q.submit(batch(8129),true,1,0));assertEquals(8129,q.heldSamples);assertEquals(1,posts.get());assertTrue(received.isEmpty())
   release.countDown();assertTrue(done.await(3,TimeUnit.SECONDS));assertEquals((0 until 8129).map{it.toShort()},received)
   val settled=CountDownLatch(1);owner.post{settled.countDown()};assertTrue(settled.await(2,TimeUnit.SECONDS));assertEquals(0,q.heldSamples)
   val dir=V2HostFixture.evidenceDirectory()
   dir.resolve("upload-handoff.json").writeText("{\"samples\":8129,\"blocks\":26,\"owner_posts\":1,\"scope\":\"real HandlerThread; production queue; live AudioRecord tested separately\"}")
  }finally{q.close();release.countDown();thread.quitSafely();thread.join(2000);assertFalse(thread.isAlive)}
 }
 @Test fun cancelUnblocksFullSampleBudgetWithoutOwnerDelivery(){
  val thread=HandlerThread("handoff-cancel").apply{start()};val owner=Handler(thread.looper);val release=CountDownLatch(1);val entered=CountDownLatch(1);val blocked=CountDownLatch(1);val done=CountDownLatch(1);val allowed=AtomicBoolean(true);val delivered=AtomicInteger()
  owner.post{entered.countDown();release.await(5,TimeUnit.SECONDS)}
  val q=CaptureUploads({owner.post(it)},{allowed.get()},{_,_,_->delivered.incrementAndGet()},{throw it},{blocked.countDown()})
  var producer:Thread?=null
  try {
   assertTrue(entered.await(2,TimeUnit.SECONDS));q.submit(batch(16000),true,1,0)
   producer=Thread{assertFalse(q.submit(batch(320),true,1,1));done.countDown()}.apply{start()}
   assertTrue(blocked.await(2,TimeUnit.SECONDS));allowed.set(false);q.close();assertTrue(done.await(2,TimeUnit.SECONDS));release.countDown()
   val drained=CountDownLatch(1);owner.post{drained.countDown()};assertTrue(drained.await(2,TimeUnit.SECONDS));assertEquals(0,delivered.get());assertEquals(0,q.heldSamples)
  }finally{allowed.set(false);q.close();release.countDown();producer?.join(2000);thread.quitSafely();thread.join(2000);assertFalse(thread.isAlive);assertFalse(producer?.isAlive==true)}
 }
}
