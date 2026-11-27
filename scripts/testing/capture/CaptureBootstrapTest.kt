package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test

class CaptureBootstrapTest {
 private class Source(var publish:Long=250) {
  var now=1000L;val origin=now;var read=0L;var reads=0;var overwritten=0L
  var cancel=false;var timestampCost=0L
  var stampOverride:((Long)->CaptureStamp?)?=null
  val references=mutableListOf<ShortArray>()
  fun produced()=(now-origin)*16
  fun stamp():CaptureStamp? {
   now+=timestampCost
   return stampOverride?.invoke(produced()) ?: if(now-origin>=publish)CaptureStamp(produced(),now*1_000_000) else null
  }
  val ledger=NativeReadLedger(3200,{now},{now},::stamp)
  val prefix=CaptureBootstrap(ledger)
  fun read(frame:ShortArray):Int {
   reads++;references+=frame
   val unread=produced()-read
   if(unread>3200){overwritten+=unread-3200;read=produced()-3200}
   val n=minOf(320L,produced()-read).toInt()
   repeat(n){frame[it]=((read+it)%30000+1).toShort()};read+=n;return n
  }
  fun prepare()=prefix.prepare(::read,{!cancel},{now+=5})
 }
 @Test fun firstStampAfter180msReadsContinuouslyAndPreservesEveryFirstSample(){
  val s=Source();s.prepare();assertTrue(s.now-s.origin>=250);assertEquals(0L,s.overwritten)
  assertTrue(s.ledger.startupAnchored.not());assertEquals(s.read,s.ledger.readSamples)
  val all=mutableListOf<Short>();val frame=ShortArray(320)
  while(s.prefix.pending){val n=s.prefix.take(frame);repeat(n){all+=frame[it]};frame.fill(0)}
  assertEquals((0 until s.read.toInt()).map{(it%30000+1).toShort()},all)
  // Sample0 coordinate is unchanged; BOOTTIME estimate now charges six extra ms.
  assertTrue(s.ledger.sampleTime(0)+1+CaptureClockBridge.LIMIT_MS in s.origin-4..s.origin)
  assertEquals(s.read,s.prefix.replayPosition);assertTrue(s.references.all{f->f.all{it==0.toShort()}})
 }
 @Test fun missingStampStopsWithinFixed500msAndWipesEverything(){
  val s=Source(Long.MAX_VALUE);val error=runCatching{s.prepare()}.exceptionOrNull()
  assertEquals("capture startup deadline",error?.message);assertEquals(500L,s.now-s.origin)
  assertTrue(s.read<=8000);assertFalse(s.prefix.pending);assertEquals(0L,s.overwritten)
  assertTrue(s.references.all{f->f.all{it==0.toShort()}})
 }
 @Test fun cancellationAndReadErrorClearUnanchoredStorage(){
  for(crash in listOf(false,true)){
   val s=Source();var calls=0
   val error=runCatching{s.prefix.prepare({frame->calls++;val n=s.read(frame)
    if(calls==3){if(crash)throw IllegalStateException("synthetic") else s.cancel=true};n},{!s.cancel},{s.now+=5})}.exceptionOrNull()
   assertNotNull(error);assertFalse(s.prefix.pending);assertTrue(s.references.all{f->f.all{it==0.toShort()}})
  }
 }
 @Test fun lateFirstStampCannotUseWindowReturnOrCounterToHideNativeLoss(){
  val s=Source();s.timestampCost=200
  val error=runCatching{s.prepare()}.exceptionOrNull()
  assertEquals("startup native continuity exhausted",error?.message);assertEquals(0,s.reads);assertFalse(s.prefix.pending)
 }
 @Test fun staleRegressingAndInvalidRateStillFailBeforeAdmission(){
  for(mode in 0..3){
   val s=Source(0);var calls=0
   s.stampOverride={p->calls++;when(mode){
    0->CaptureStamp(0,(s.now-101)*1_000_000)
    1->CaptureStamp(if(calls<6)p else p-1,s.now*1_000_000)
    2->CaptureStamp(p/2,s.now*1_000_000)
    else->CaptureStamp(p,s.now*1_000_000-600_000_000)
   }}
   val error=runCatching{s.prepare()}.exceptionOrNull()
   assertNotNull("mode$mode",error);if(mode==1)assertEquals("capture timestamp regressed",error?.message)
   assertFalse(s.prefix.pending)
  }
 }
 @Test fun slowUnanchoredReadGapsAccumulateRatherThanRefreshNativeBudget(){
  val s=Source(Long.MAX_VALUE)
  val error=runCatching{s.prefix.prepare({frame->s.now+=100;s.read(frame)},{true},{s.now+=5})}.exceptionOrNull()
  assertNotNull(error);assertTrue(s.reads<5);assertFalse(s.prefix.pending)
 }
 @Test fun successfulStampReturnedAtStartupDeadlineCannotAdmitPrefix(){
  val s=Source(0);s.timestampCost=500
  assertEquals("capture startup deadline",runCatching{s.prepare()}.exceptionOrNull()?.message)
  assertFalse(s.prefix.pending)
 }
 @Test fun realCaptureDoesNotDecodeOrUploadUnanchoredPcmAndReplaysFirstFrame(){
  android.media.AudioRecord.reset(50);android.media.AudioRecord.stampAvailableAfterMs=250
  com.littlebuddy.SherpaWake.detectAfter=21
  val handler=android.os.Handler();val client=VoiceClient();val seen=mutableListOf<Short>();var failures=0
  com.littlebuddy.SherpaWake.observe={frame,_->seen+=frame[0]}
  android.media.AudioRecord.onRead={
   if(android.os.SystemClock.manualNow-100000<250){assertTrue(seen.isEmpty());assertTrue(client.received.isEmpty())}
  }
  val capture=Capture(android.content.res.AssetManager(),handler,client,{true}){failures++}
  capture.start()
  try {
   val until=System.nanoTime()+3_000_000_000
   while(capture.nativeProof.frames<16000 && !capture.nativeProof.released && System.nanoTime()<until)Thread.sleep(5)
   handler.drain();assertEquals(0,failures);assertTrue(capture.nativeProof.frames>=16000)
   assertEquals((1..21).map{it.toShort()},seen);assertTrue(client.received.isNotEmpty())
   assertEquals(1.toShort(),client.received.first().first())
  }finally{capture.close();handler.drain();com.littlebuddy.SherpaWake.observe={_,_->}}
 }
 @Test fun cacheIsPhysicallyClearedOnFailureAndExplicitCancellation(){
  for(cancel in listOf(false,true)) {
   val s=Source(Long.MAX_VALUE)
   if(cancel)s.cancel=true
   runCatching{s.prepare()}
   val field=CaptureBootstrap::class.java.getDeclaredField("pcm");field.isAccessible=true
   assertTrue((field.get(s.prefix) as ShortArray).all{it==0.toShort()})
   assertFalse(s.prefix.pending)
  }
 }
 @Test fun callerCancellationWipesCacheWithoutWaitingForBlockedNativeWorker(){
  val s=Source(Long.MAX_VALUE);val blocked=java.util.concurrent.CountDownLatch(1);val release=java.util.concurrent.CountDownLatch(1)
  var calls=0;var failure:Throwable?=null
  val thread=Thread{failure=runCatching{s.prefix.prepare({frame->calls++;if(calls==3){blocked.countDown();release.await()};s.read(frame)},{true},{s.now+=5})}.exceptionOrNull()}
  thread.start()
  try {
   assertTrue(blocked.await(2,java.util.concurrent.TimeUnit.SECONDS));s.prefix.clear()
   val field=CaptureBootstrap::class.java.getDeclaredField("pcm");field.isAccessible=true
   assertTrue((field.get(s.prefix) as ShortArray).all{it==0.toShort()});assertTrue(thread.isAlive)
  }finally{release.countDown();thread.join(2000)}
  assertFalse(thread.isAlive);assertNotNull(failure);assertFalse(s.prefix.pending)
  assertTrue(s.references.all{f->f.all{it==0.toShort()}})
 }
 @Test fun newTimestampCannotAdmitAlreadyReadInconsistentPrefixBeforeAnotherNativeRead(){
  var now=1000L;var reads=0;var delayPublish=false
  val ledger=NativeReadLedger(3200,{now},{now}){
   if(reads==0)null else {
    val narrowed=reads==3 && delayPublish
    if(reads==3)delayPublish=true
    if(narrowed)CaptureStamp(641,1_041_000_000) else CaptureStamp(640,1_040_000_000)
   }
  }
  val prefix=CaptureBootstrap(ledger);val refs=mutableListOf<ShortArray>()
  val error=runCatching{prefix.prepare({frame->
   now=1041;reads++;refs+=frame;val count=if(reads<3)320 else 32
   frame.fill(7);count
  },{true},{})}.exceptionOrNull()
  assertEquals("native read exceeds timestamp position",error?.message)
  assertEquals(672L,ledger.readSamples);assertEquals(3,reads);assertFalse(prefix.pending)
  val field=CaptureBootstrap::class.java.getDeclaredField("pcm");field.isAccessible=true
  assertTrue((field.get(prefix) as ShortArray).all{it==0.toShort()})
  assertTrue(refs.all{it.all{sample->sample==0.toShort()}})
 }

}
