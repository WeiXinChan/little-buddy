package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
import android.media.AudioRecord
import android.os.SystemClock
import android.os.Handler
import android.content.res.AssetManager
import com.littlebuddy.SherpaWake

/** Production Capture+ledger, controlled native source; no Android hardware claim. */
class StartupBoundaryTest {
 private fun run(mode:String,expectReady:Boolean) {
  AudioRecord.reset(24);AudioRecord.actualFramesOverride=3200;SherpaWake.detectAfter=21
  val lock=Capture::class.java.getDeclaredField("nativeLock").apply{isAccessible=true}
  var injected=false;var errors=0;var modelDone=false
  AbsoluteWake.initializeHook={SystemClock.manualNow+=1385;modelDone=true}
  AbsoluteWake.rearmHook={}
  val owner=Handler();val client=VoiceClient();lateinit var capture:Capture
  if(mode=="start")AudioRecord.beforeStart={SystemClock.manualNow+=181}
  if(mode=="read")AudioRecord.onRead={if(it==1)SystemClock.manualNow+=181}
  capture=Capture(AssetManager(),owner,client,{
   if(mode=="before" && modelDone && !injected && Thread.holdsLock(lock.get(capture))){injected=true;SystemClock.manualNow+=181}
   true
  }){errors++}
  capture.start()
  try {
   val until=System.nanoTime()+3_000_000_000
   while(capture.nativeProof.frames<24*320 && !capture.nativeProof.released && System.nanoTime()<until)Thread.sleep(3)
   owner.drain()
   if(expectReady){val postedUntil=System.nanoTime()+1_000_000_000
    while(client.received.isEmpty() && System.nanoTime()<postedUntil){owner.drain();Thread.sleep(1)}
   }
   if(expectReady){assertEquals(0,errors);assertTrue(capture.nativeProof.frames>=21*320);assertEquals(1.toShort(),client.received.first()[0])}
   else {assertTrue(errors>0);assertTrue(client.received.isEmpty());assertTrue(capture.nativeProof.released)}
   if(mode=="before")assertTrue(injected)
  }finally{capture.close();owner.drain();AbsoluteWake.initializeHook={};assertTrue(ProcessRecorders.released())}
 }
 @Test fun allocationAndFinalAdmissionBeforeStartCannotConsumeNativeFifo()=run("before",true)
 @Test fun modelInitializationIsNotNativeRecordingTime()=run("model",true)
 @Test fun unknownNativeStartIntervalStillConsumesFullBudget()=run("start",false)
 @Test fun returnedNativeReadCannotHideExpiredBudget()=run("read",false)
}
