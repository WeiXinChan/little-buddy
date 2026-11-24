package com.littlebuddy.v2
import org.junit.Test
import org.junit.Assert.*
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
class CaptureUploadsTest {
 private fun frames(n:Int)=List((n+319)/320){i->ShortArray(minOf(320,n-i*320)){j->(i*320+j).toShort()}}
 @Test fun pausedOwner8129Samples26BlocksAreDeliveredExactlyOnce(){
  val tasks=ArrayDeque<()->Unit>();val received=mutableListOf<Short>();val input=frames(8129)
  val q=CaptureUploads({tasks.add(it);true},{true},{data,_,_->received.addAll(data.toList())},{throw it})
  assertTrue(q.submit(input,true,7,12));assertEquals(1,tasks.size);assertEquals(8129,q.heldSamples)
  tasks.removeFirst()();assertEquals((0 until 8129).map{it.toShort()},received);assertEquals(0,q.heldSamples);assertTrue(input.all{f->f.all{it==0.toShort()}});assertTrue(tasks.isEmpty())
 }
 @Test fun fullRingBackpressureWaitsThenRetainsAllSampleOrder(){
  val tasks=java.util.concurrent.LinkedBlockingQueue<()->Unit>();val blocked=CountDownLatch(1);val done=CountDownLatch(1);var total=0
  val q=CaptureUploads({tasks.add(it);true},{true},{d,_,_->total+=d.size},{throw it},{blocked.countDown()})
  q.submit(frames(16000),true,1,0)
  val producer=Thread{assertTrue(q.submit(frames(320),true,1,1));done.countDown()}.apply{start()}
  assertTrue(blocked.await(2,TimeUnit.SECONDS));assertEquals(16000,q.heldSamples);assertEquals(1,tasks.size)
  tasks.take()();assertTrue(done.await(2,TimeUnit.SECONDS));tasks.take()();producer.join(1000);assertEquals(16320,total);assertEquals(0,q.heldSamples)
 }
 @Test fun cancellationUnblocksProducerAndDropsOnlyCancelledOwnership(){
  val allowed=AtomicBoolean(true);val blocked=CountDownLatch(1);val done=CountDownLatch(1);val tasks=ArrayDeque<()->Unit>();var delivered=0;val next=frames(320)
  val q=CaptureUploads({tasks.add(it);true},{allowed.get()},{d,_,_->delivered+=d.size},{throw it},{blocked.countDown()})
  q.submit(frames(16000),true,1,0);val producer=Thread{assertFalse(q.submit(next,true,1,1));done.countDown()}.apply{start()}
  assertTrue(blocked.await(2,TimeUnit.SECONDS));allowed.set(false);q.invalidate();assertTrue(done.await(2,TimeUnit.SECONDS));producer.join(1000)
  tasks.removeFirst()();assertEquals(0,delivered);assertEquals(0,q.heldSamples);assertTrue(next.all{f->f.all{it==0.toShort()}})
 }
 @Test fun managementAndGenerationRecheckedBetweenChunks(){
  var generation=1L;val tasks=ArrayDeque<()->Unit>();var delivered=0
  val q=CaptureUploads({tasks.add(it);true},{it==generation},{d,_,_->delivered+=d.size;generation=2},{throw it})
  q.submit(frames(8129),true,1,0);tasks.removeFirst()();assertEquals(320,delivered);assertEquals(0,q.heldSamples)
 }
 @Test fun ownerRejectionCannotKeepSamples(){val q=CaptureUploads({false},{true},{_,_,_->},{throw it});try{q.submit(frames(320),true,1,0);fail()}catch(_:IllegalStateException){};assertEquals(0,q.heldSamples)}
 @Test fun interruptedProducerWipesOnlyItsUnsubmittedBatch(){
  val blocked=CountDownLatch(1);val done=CountDownLatch(1);val next=frames(320)
  val q=CaptureUploads({true},{true},{_,_,_->},{throw it},{blocked.countDown()})
  q.submit(frames(16000),true,1,0)
  val producer=Thread{try{q.submit(next,true,1,1);fail()}catch(_:InterruptedException){}finally{done.countDown()}}.apply{start()}
  assertTrue(blocked.await(2,TimeUnit.SECONDS));producer.interrupt();assertTrue(done.await(2,TimeUnit.SECONDS));producer.join(1000)
  assertTrue(next.all{f->f.all{it==0.toShort()}});assertEquals(16000,q.heldSamples);q.close();assertEquals(0,q.heldSamples)
 }
 @Test fun deliveryFailureClosesQueueAndReturnsSampleBudget(){
  val tasks=ArrayDeque<()->Unit>();var failures=0
  val q=CaptureUploads({tasks.add(it);true},{true},{_,_,_->throw IllegalStateException("not logged")},{failures++})
  q.submit(frames(8129),true,1,0);tasks.removeFirst()();assertEquals(1,failures);assertEquals(0,q.heldSamples);assertFalse(q.submit(frames(320),true,1,0))
 }
 @Test fun nativeRetentionBudgetIsConservative(){assertEquals(100L,NativeRetention.budgetMs(3200,0,0));assertEquals(20L,NativeRetention.budgetMs(3200,2400,10));assertEquals(0L,NativeRetention.budgetMs(3200,null,0));assertEquals(0L,NativeRetention.budgetMs(3200,0,41));assertEquals(0L,NativeRetention.budgetMs(3200,3000,0))}
 @Test fun pausedOwnerHasFixedCumulativeDeadlineEvenWhenEligible(){
  val clock=java.util.concurrent.atomic.AtomicLong();val entered=CountDownLatch(1);val done=CountDownLatch(1);val frames=frames(320);val tasks=ArrayDeque<()->Unit>();var delivered=0
  val q=CaptureUploads({tasks.add(it);true},{true},{_,_,_->delivered++},{throw it},{entered.countDown()},now={clock.get()})
  q.submit(this.frames(16000),true,1,0)
  val producer=Thread{try{q.submit(frames,true,1,1){50};fail()}catch(_:InputContinuityInterrupted){}finally{done.countDown()}}.apply{start()}
  assertTrue(entered.await(1,TimeUnit.SECONDS));clock.set(51);assertTrue(done.await(1,TimeUnit.SECONDS));producer.join(1000)
  tasks.removeFirst()();assertEquals(0,delivered);assertEquals(0,q.heldSamples);assertTrue(frames.all{f->f.all{it==0.toShort()}})
 }
 @Test fun activeQueuedWaitingManagementCancellationCannotSendNextChunk()=activeCancellation(false)
 @Test fun activeQueuedWaitingHomeCancellationCannotSendNextChunk()=activeCancellation(true)
 private fun activeCancellation(home:Boolean){
  val tasks=java.util.concurrent.LinkedBlockingQueue<()->Unit>();val active=CountDownLatch(1);val resume=CountDownLatch(1);val blocked=CountDownLatch(1);val done=CountDownLatch(1);val allowed=AtomicBoolean(true);var sent=0
  val q=CaptureUploads({tasks.add(it);true},{allowed.get()},{_,_,_->sent++;active.countDown();resume.await(2,TimeUnit.SECONDS)},{throw it},{blocked.countDown()})
  q.submit(frames(8129),true,1,0);val consumer=Thread{tasks.take()()}.apply{start()};assertTrue(active.await(1,TimeUnit.SECONDS));q.submit(frames(7871),true,1,0)
  val producer=Thread{assertFalse(q.submit(frames(320),true,1,0));done.countDown()}.apply{start()}
  assertTrue(blocked.await(1,TimeUnit.SECONDS));allowed.set(false);if(home)q.close()else q.invalidate();assertTrue(done.await(1,TimeUnit.SECONDS));resume.countDown();consumer.join(1000);producer.join(1000);assertEquals(1,sent);assertEquals(0,q.heldSamples)
  allowed.set(true);if(home)assertFalse(q.submit(frames(320),true,2,0)) else {assertTrue(q.submit(frames(320),true,2,0));tasks.take()();assertEquals(2,sent)}
 }
 @Test fun cancellationDuringNativeBudgetQueryIsNotInputFailure(){
  val allowed=AtomicBoolean(true);val q=CaptureUploads({true},{allowed.get()},{_,_,_->},{throw it})
  q.submit(frames(16000),true,1,0)
  assertFalse(q.submit(frames(320),true,1,0){allowed.set(false);0L});q.close();assertEquals(0,q.heldSamples)
 }
 @Test fun safeFailureNeverContainsMessageOrForeignFrame(){val e=IllegalStateException("PRIVATE_SENTINEL");e.stackTrace=arrayOf(StackTraceElement("foreign.Secret","PRIVATE_SENTINEL","Secret.kt",9),StackTraceElement("com.littlebuddy.v2.Capture","record","Capture.kt",11));val s=SafeFailure.describe(e);assertFalse(s.contains("PRIVATE_SENTINEL"));assertFalse(s.contains("foreign"));assertTrue(s.contains("Capture.kt:11"))}
}
