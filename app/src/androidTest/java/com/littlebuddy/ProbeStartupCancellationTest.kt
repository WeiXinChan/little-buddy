package com.littlebuddy
import com.littlebuddy.v2.*
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

class ProbeStartupCancellationTest {
 private fun blockedRead(cancelBeforeInstall:Boolean) {
  var now=1000L;var read=0L;var calls=0
  val cancelled=AtomicBoolean(false);val control=ProbeStartupCancellation(cancelled)
  val ledger=NativeReadLedger(3200,{now},{now}){null};val prefix=CaptureBootstrap(ledger)
  val entered=CountDownLatch(1);val release=CountDownLatch(1)
  val frames=mutableListOf<ShortArray>();var failure:Throwable?=null
  if(!cancelBeforeInstall)control.install(prefix)
  val worker=Thread {
   failure=runCatching{prefix.prepare({frame->
    if(++calls==3){entered.countDown();release.await()}
    frames+=frame
    val count=minOf(320L,(now-1000)*16-read).toInt()
    frame.fill(7);read+=count;count
   },{!cancelled.get()},{now+=5})}.exceptionOrNull()
  }
  worker.start()
  val field=CaptureBootstrap::class.java.getDeclaredField("pcm").apply{isAccessible=true}
  try {
   assertTrue(entered.await(2,TimeUnit.SECONDS))
   assertTrue((field.get(prefix) as ShortArray).any{it!=0.toShort()})
   control.cancel()
   if(cancelBeforeInstall)control.install(prefix)
   assertTrue(cancelled.get());assertTrue(worker.isAlive)
   assertTrue((field.get(prefix) as ShortArray).all{it==0.toShort()})
   assertFalse(prefix.pending)
  }finally{release.countDown();worker.join(2000);control.clear()}
  assertFalse(worker.isAlive);assertNotNull(failure)
  assertTrue(frames.all{it.all{sample->sample==0.toShort()}})
 }
 @Test fun foregroundTimeoutOrFinallyCancelClearsBeforeNativeReadReturns()=blockedRead(false)
 @Test fun cancelBeforeRegistrationCannotLeavePrefixUncleared()=blockedRead(true)
}
