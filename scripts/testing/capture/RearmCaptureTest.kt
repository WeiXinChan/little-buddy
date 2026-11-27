package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
import android.media.AudioRecord
import android.os.Handler
import android.content.res.AssetManager
import com.littlebuddy.SherpaWake
class RearmCaptureTest {
 private fun await(test:()->Boolean){val end=System.nanoTime()+3_000_000_000;while(!test()&&System.nanoTime()<end)Thread.sleep(5);assertTrue(test())}
 @Test fun rearmMustNotReloadWholeModelWhileNativeRecorderRuns(){
  AudioRecord.reset(3);SherpaWake.detectAfter=1
  AbsoluteWake.initialized=0;AbsoluteWake.rearmed=0
  // Same 1399ms read gap as the hardware observation, injected only into a second model load.
  AbsoluteWake.initializeHook={if(it>1){android.os.SystemClock.manualNow+=1399;Thread.sleep(20)}}
  val h=Handler();val c=VoiceClient();var errors=0
  val clock=java.util.concurrent.CopyOnWriteArrayList<CaptureClockReason>();CaptureClockDiagnostic.install{clock.add(it.reason)}
  AudioRecord.onRead={if(it==2)c.idleSerial++}
  val cap=Capture(AssetManager(),h,c,{true}){errors++};cap.start()
  try {await{cap.nativeProof.frames>=640};Thread.sleep(100);h.drain()
   println("REARM_BEHAVIOR initialized=${AbsoluteWake.initialized} failures=$errors wakes=${c.wakes.size} released=${cap.nativeProof.released} clock=$clock")
   assertEquals("no clock failure during rearm",0,errors)
   assertEquals("second wake must retain original coordinate",2,c.wakes.size)
   assertEquals("one model lifetime per recorder",1,AbsoluteWake.initialized)
   assertEquals("new stream at first sample of rearm frame",1,AbsoluteWake.rearmed)
   assertEquals(0,errors);assertEquals(2,c.wakes.size)
  }finally{cap.close();h.drain();AbsoluteWake.initializeHook={};CaptureClockDiagnostic.install(null)}
 }

}
