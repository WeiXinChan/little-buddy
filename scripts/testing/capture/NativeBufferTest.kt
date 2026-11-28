package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
import android.media.AudioRecord
import android.os.SystemClock
import android.os.Handler
import android.content.res.AssetManager
import com.littlebuddy.SherpaWake
import com.littlebuddy.v2.parent.PinDiagnostic

class NativeBufferTest {
 private fun run(warmup:Long=0,startDelay:Long=0,actual:Int=-1,missing:Boolean=false,body:(Capture,VoiceClient,Int)->Unit) {
  AudioRecord.reset(if(missing)100 else 24);AudioRecord.actualFramesOverride=actual;AudioRecord.readWarmupMs=warmup
  AudioRecord.beforeStart={SystemClock.manualNow+=startDelay}
  if(missing)AudioRecord.stampAvailableAfterMs=Long.MAX_VALUE
  SherpaWake.detectAfter=21;SherpaWake.observe={_,_->};AbsoluteWake.initializeHook={};AbsoluteWake.rearmHook={}
  val allocations=java.util.concurrent.CopyOnWriteArrayList<PinDiagnostic.RuntimeEvent>()
  PinDiagnostic.installRuntime{if(it.stage==PinDiagnostic.RuntimeStage.CAPTURE_BUFFER)allocations+=it}
  val h=Handler();val client=VoiceClient();var errors=0;val c=Capture(AssetManager(),h,client,{true}){errors++}
  c.start()
  try {
   val end=System.nanoTime()+3_000_000_000
   while(!c.nativeProof.released && c.nativeProof.frames<24*320 && System.nanoTime()<end)Thread.sleep(2)
   val drainEnd=System.nanoTime()+500_000_000
   do{h.drain();if(c.nativeProof.released || client.received.isNotEmpty())break;Thread.sleep(1)}while(System.nanoTime()<drainEnd)
   val error=c.lastClockFailure
   println("BUFFER_OBS warmup=$warmup start_delay=$startDelay request=${AudioRecord.requestedBytes} actual_override=$actual reason=${error?.reason} reads=${error?.evidence?.reads} native_returned=${error?.context?.nativeReturnedSamples} calls=${error?.context?.nativeReadCalls} released=${c.nativeProof.released}")
   if(error==null){
    val allocation=allocations.single();assertEquals(AudioRecord.requestedBytes/2,allocation.requestedNativeFrames)
    assertEquals(minOf(allocation.requestedNativeFrames,allocation.actualNativeFrames),allocation.creditedNativeFrames)
   }
   body(c,client,errors)
  }finally{c.close();h.drain();PinDiagnostic.installRuntime(null);assertTrue(ProcessRecorders.released())}
 }
 @Test fun requestBacksWholeStartupUpperBoundAndCreditNeverExceedsPhysicalCapacity(){
  assertEquals(17280,NativeCaptureBuffer.requestedBytes(1280))
  assertEquals(32000,NativeCaptureBuffer.requestedBytes(31999))
  assertEquals(3200,NativeCaptureBuffer.verifiedFrames(17280,3200))
  assertEquals(8640,NativeCaptureBuffer.verifiedFrames(17280,16000))
  assertEquals(8640,NativeCaptureBuffer.verifiedFrames(17280,32768))
  assertThrows(IllegalArgumentException::class.java){NativeCaptureBuffer.verifiedFrames(17280,320)}
  assertThrows(IllegalArgumentException::class.java){NativeCaptureBuffer.requestedBytes(32001)}
 }
 @Test fun nativeStartAndEmptyReadWarmupExceedOldRoomButAnchorWithoutLosingSampleOne()=
  run(warmup=150,startDelay=35){c,client,errors->
   assertEquals(0,errors);assertEquals(17280,AudioRecord.requestedBytes);assertNull(c.lastClockFailure)
   assertTrue(c.nativeProof.frames>=24*320);assertEquals(1.toShort(),client.received.first()[0])
   assertEquals(0,AudioRecord.overwritten.get())
  }
 @Test fun smallerActualAllocationCannotBorrowRequestedRoom()=run(warmup=150,startDelay=35,actual=3200){c,client,errors->
  assertTrue(errors>0);assertEquals(3200,c.lastClockFailure!!.evidence.capacity)
  assertEquals(CaptureClockReason.STARTUP_NATIVE_CONTINUITY_EXHAUSTED,c.lastClockFailure!!.reason)
  assertTrue(client.received.isEmpty());assertTrue(c.nativeProof.released)
 }
 @Test fun noTimestampStillStopsAtOriginal500msAndNeverUploads()=run(missing=true){c,client,errors->
  assertTrue(errors>0);assertEquals(CaptureClockReason.STARTUP_DEADLINE,c.lastClockFailure!!.reason)
  assertTrue(c.lastClockFailure!!.evidence.reads<=8000);assertTrue(client.received.isEmpty());assertTrue(c.nativeProof.released)
 }
 @Test fun nativeJniBeyondStartupDeadlineStillFails()=run(startDelay=501){c,client,errors->
  assertTrue(errors>0);assertEquals(CaptureClockReason.STARTUP_DEADLINE,c.lastClockFailure!!.reason)
  assertTrue(client.received.isEmpty());assertTrue(c.nativeProof.released)
 }
 @Test fun extraNativeStorageCannotExtendOriginalUploadAge(){
  var now=2201L;var accepted=0;var failures=0;val jobs=java.util.ArrayDeque<Runnable>()
  val q=CaptureUploads({jobs.add(it);true},{now},{true},{_,_,_->accepted++},{failures++})
  q.nativeRoom(17280);val pcm=ShortArray(320){7};q.offer(listOf(pcm),true,1000)
  while(jobs.isNotEmpty())jobs.removeFirst().run()
  assertEquals(0,accepted);assertEquals(1,failures);assertTrue(pcm.all{it==0.toShort()})
 }
 @Test fun timestampAgeStill100msWithLargerRealBuffer(){
  var now=1000L;val ledger=NativeReadLedger(8640,{now},{now}){CaptureStamp(0,1_000_000_000)}
  ledger.check();now=1101
  assertEquals(CaptureClockReason.TIMESTAMP_STALE,(runCatching{ledger.check()}.exceptionOrNull() as CaptureClockFailure).reason)
 }
 @Test fun realNativeOverwriteStillRejectsWithoutUploading(){
  AudioRecord.reset(0);AudioRecord.continuous=true;SystemClock.realtime=true;AudioRecord.timestampDelayMs=650
  SherpaWake.detectAfter=100000;AbsoluteWake.initializeHook={}
  val allocations=java.util.concurrent.CopyOnWriteArrayList<PinDiagnostic.RuntimeEvent>()
  PinDiagnostic.installRuntime{if(it.stage==PinDiagnostic.RuntimeStage.CAPTURE_BUFFER)allocations+=it}
  val h=Handler();val client=VoiceClient();var errors=0;val c=Capture(AssetManager(),h,client,{true}){errors++};c.start()
  try{
   val until=System.nanoTime()+3_000_000_000
   while(!c.nativeProof.released && System.nanoTime()<until)Thread.sleep(3)
   h.drain();assertTrue(errors>0);assertTrue(AudioRecord.overwritten.get()>0)
   assertTrue(c.nativeProof.released);assertTrue(client.received.isEmpty())
  }finally{c.close();h.drain();SystemClock.realtime=false;assertTrue(ProcessRecorders.released())}
 }
}
