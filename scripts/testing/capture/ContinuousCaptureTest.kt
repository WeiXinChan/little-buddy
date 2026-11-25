package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
import android.media.AudioRecord
import android.os.Handler
import android.os.SystemClock
import android.content.res.AssetManager
import com.littlebuddy.SherpaWake
class ContinuousCaptureTest {
 private fun continuous(slow:(Int)->Long,detect:Int=100000,configure:()->Unit={},body:(Capture,Handler,VoiceClient,()->Int)->Unit) {
  AudioRecord.reset(0);AudioRecord.continuous=true;SystemClock.realtime=true
  SherpaWake.detectAfter=detect;SherpaWake.delayForRead=slow
  val h=Handler();val client=VoiceClient();var failures=0
  val c=Capture(AssetManager(),h,client,{true}){failures++};configure();c.start()
  try{body(c,h,client,{failures})}finally{
   c.close();h.drain();AudioRecord.producer?.join(1000)
   SherpaWake.delayForRead={SherpaWake.delayMs};SherpaWake.delayMs=0;SystemClock.realtime=false
  }
 }
 @Test fun sustained100msPerReadMustFailBeforeSilentNativeOverwrite()=continuous({100}) {cap,h,_,failures->
  Thread.sleep(900);h.drain()
  println("continuous slow: overwritten=${AudioRecord.overwritten.get()} released=${cap.nativeProof.released} failures=${failures()}")
  assertTrue("slow consumer must fail explicitly",failures()>0)
  assertTrue("recorder must release on continuity failure",cap.nativeProof.released)
 }
 @Test fun shortBurstThenCatchUpRemainsContinuous()=continuous({if(it==1)60L else 0L}) {cap,h,_,failures->
  Thread.sleep(350);h.drain()
  assertEquals(0,AudioRecord.overwritten.get());assertEquals(0,failures());assertFalse(cap.nativeProof.released)
 }

 @Test fun catchUpSamplesKeepOriginalHardwareAgeRatherThanReadReturnTime()=continuous({if(it==1)60L else 0L},detect=2){_,h,client,failures->
  Thread.sleep(300);h.drain();assertEquals(0,failures());assertTrue(client.received.isNotEmpty())
  val first=client.received.first();val lastSample=first.last().toInt() and 65535
  val sampleEndMs=AudioRecord.captureOriginNs/1_000_000+lastSample/16
  println("hardware age: sampleEnd=$sampleEndMs accepted=${client.capturedTimes.first()}")
  assertTrue("cached PCM must not be retagged as freshly read",client.capturedTimes.first()<=sampleEndMs)
 }

 @Test fun delayedStartUsesHardwareCountAndRejectsBufferFilledInsideBlockedStart(){
  for(phase in 0..2)continuous({0},configure={
   when(phase){0->AudioRecord.beforeStart={Thread.sleep(300)};1->AudioRecord.afterStart={Thread.sleep(300)};else->AudioRecord.timestampDelayMs=80}
  }){cap,h,client,failures->
   val end=System.nanoTime()+2_000_000_000
   if(phase!=1){
    while(cap.nativeProof.frames<640&&System.nanoTime()<end)Thread.sleep(5)
    h.drain();assertTrue(cap.nativeProof.frames>=640);assertEquals(0,failures());assertFalse(cap.nativeProof.released)
   }else{
    while(!cap.nativeProof.released&&System.nanoTime()<end)Thread.sleep(5)
    h.drain();assertTrue(cap.nativeProof.released);assertTrue(failures()>0);assertTrue(client.received.isEmpty())
   }
  }
 }
}
