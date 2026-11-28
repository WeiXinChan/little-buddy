package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
import android.media.AudioRecord
import android.os.Handler
import android.os.SystemClock
import android.content.res.AssetManager
import com.littlebuddy.SherpaWake

class ExpiryStartupTest {
 private data class Result(val capture:Capture,val handler:Handler,val client:VoiceClient)
 private fun record(fault:Boolean):Result {
  AudioRecord.reset(24);SherpaWake.detectAfter=21;AbsoluteWake.initializeHook={};AbsoluteWake.rearmHook={}
  if(fault){AudioRecord.stampAvailableAfterMs=2000;AudioRecord.onRead={if(it==1)SystemClock.manualNow+=181}}
  val handler=Handler();val client=VoiceClient()
  val capture=Capture(AssetManager(),handler,client,{true}){}
  capture.start();val until=System.nanoTime()+3_000_000_000
  while(!capture.nativeProof.released && capture.nativeProof.frames<24*320 && System.nanoTime()<until)Thread.sleep(3)
  if(!fault){val postedUntil=System.nanoTime()+1_000_000_000
   while(client.received.isEmpty() && System.nanoTime()<postedUntil){handler.drain();Thread.sleep(1)}
  }
  capture.close();handler.drain();assertTrue(ProcessRecorders.released())
  return Result(capture,handler,client)
 }
 @Test fun expiredOldLeaseReleasedThenSingleFreshRetryCanAnchorAndReplaySampleOne(){
  val old=record(false);assertTrue(old.capture.nativeProof.released)
  val budget=ExpiryCaptureRestart();budget.arm(1);budget.started(1,3)
  val failed=record(true);val error=failed.capture.lastClockFailure!!
  assertEquals(CaptureClockReason.STARTUP_NATIVE_CONTINUITY_EXHAUSTED,error.reason)
  assertEquals(0L,error.evidence.reads);assertEquals(320L,error.context!!.nativeReturnedSamples)
  assertEquals(1L,error.context.nativeReadCalls);assertEquals(320,error.context.lastNativeReadCount)
  assertEquals(0,error.context.prefixCachedSamplesTotal)
  assertTrue(budget.consume(1,3,error.reason,true,true,ProcessRecorders.released()))
  budget.started(1,4);val fresh=record(false)
  assertNull(fresh.capture.lastClockFailure);assertEquals(1.toShort(),fresh.client.received.first()[0])
 }
 @Test fun persistentPostStartFailureStopsAfterOneRetry(){
  val budget=ExpiryCaptureRestart();budget.arm(1);budget.started(1,3)
  val first=record(true)
  assertTrue(budget.consume(1,3,first.capture.lastClockFailure!!.reason,true,true,ProcessRecorders.released()))
  budget.started(1,4);val second=record(true)
  assertFalse(budget.consume(1,4,second.capture.lastClockFailure!!.reason,true,true,ProcessRecorders.released()))
  assertTrue(second.capture.nativeProof.released);assertTrue(second.client.received.isEmpty())
 }
 @Test fun focusCancellationAndMissingReleaseNeverAuthorizeRestart(){
  for(mode in 0..2){
   val b=ExpiryCaptureRestart();b.arm(1);b.started(1,3);val first=record(true)
   if(mode==0)b.cancel()
   assertFalse(b.consume(1,3,first.capture.lastClockFailure!!.reason,mode!=1,true,mode!=2))
   assertTrue(ProcessRecorders.released())
  }
 }
 @Test fun wrongScopeNonStartupAndAwakeDoNotBorrowExpiryPermission(){
  val b=ExpiryCaptureRestart();b.arm(1);b.started(1,3)
  assertFalse(b.consume(2,3,CaptureClockReason.STARTUP_NATIVE_CONTINUITY_EXHAUSTED,true,true,true))
  assertFalse(b.consume(1,4,CaptureClockReason.STARTUP_NATIVE_CONTINUITY_EXHAUSTED,true,true,true))
  assertFalse(b.consume(1,3,CaptureClockReason.TIMESTAMP_STALE,true,true,true))
  assertFalse(b.consume(1,3,CaptureClockReason.STARTUP_NATIVE_CONTINUITY_EXHAUSTED,true,false,true))
 }
 @Test fun actual181msSnapshotHasDistinctUnknownReadCountBoundaries(){
  for(count in listOf(0,35,36,52)){
   var now=1000L;val ledger=NativeReadLedger(3200,{now},{now}){null};ledger.beginStartup()
   now=1175;ledger.stageRead(count);now=1181
   val failure=runCatching{ledger.remainingMs()}.exceptionOrNull() as? CaptureClockFailure
   if(count<=35)assertEquals(CaptureClockReason.STARTUP_NATIVE_CONTINUITY_EXHAUSTED,failure?.reason)
   else if(count==36)assertEquals(CaptureClockReason.STARTUP_NATIVE_ROOM_EXHAUSTED,failure?.reason)
   else {assertNull(failure);assertEquals(1L,ledger.remainingMs())}
  }
 }
 @Test fun absentExpiryPermissionCannotTurnOrdinaryStartupFailureIntoRetry(){
  val b=ExpiryCaptureRestart();b.started(1,3)
  assertFalse(b.consume(1,3,CaptureClockReason.STARTUP_NATIVE_CONTINUITY_EXHAUSTED,true,true,true))
 }
 @Test fun nativeStartBoundaryCannotBeResetAfterUnknownJniOrAfterReads(){
  var now=1000L;val ledger=NativeReadLedger(3200,{now},{now}){null};ledger.beginStartup()
  now+=181;assertEquals(now,ledger.armNativeStart())
  assertThrows(IllegalStateException::class.java){ledger.armNativeStart()}
  now+=181
  assertEquals(CaptureClockReason.STARTUP_NATIVE_CONTINUITY_EXHAUSTED,(runCatching{ledger.remainingMs()}.exceptionOrNull() as CaptureClockFailure).reason)
 }
}
