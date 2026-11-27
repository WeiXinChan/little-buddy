package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
import android.media.AudioRecord
import android.content.res.AssetManager
import android.os.Handler
import com.littlebuddy.SherpaWake
import java.util.concurrent.CountDownLatch
class OriginalCaptureTest {
 private fun await(test:()->Boolean){val end=System.nanoTime()+3_000_000_000;while(!test()&&System.nanoTime()<end)Thread.sleep(5);assertTrue(test())}
 private fun batch(n:Int){AudioRecord.reset(n);SherpaWake.detectAfter=n;val h=Handler();val c=VoiceClient();var errors=0
  val cap=Capture(AssetManager(),h,c,{true}){errors++};cap.start()
  try {await{cap.nativeProof.frames>=n*320L};Thread.sleep(50);h.drain();assertEquals(n,c.received.size);assertEquals(0,errors);assertEquals("wake",c.order.first())}finally{cap.close();h.drain()}
 }
 @Test fun delayedOwner21FramesRemainValid()=batch(21)
 @Test fun delayedOwner50FramesRemainValid()=batch(50)
 @Test fun oldWorkerCannotOverlapNewActivityRecorder(){AudioRecord.reset(1);SherpaWake.detectAfter=100;val block=CountDownLatch(1);SherpaWake.blockClose=block
  val h=Handler();val a=Capture(AssetManager(),h,VoiceClient(),{true}){};a.start();await{AudioRecord.active.get()==1};a.close()
  val b=Capture(AssetManager(),h,VoiceClient(),{true}){}
  try {runCatching{b.start()};Thread.sleep(100);assertTrue(AudioRecord.maximum.get()<=1)}finally{SherpaWake.blockClose=null;block.countDown();a.close();b.close();h.drain()}
 }
 @Test fun reWakeOriginIsFirstSampleOfAlreadyPushedFrame(){AudioRecord.reset(2);SherpaWake.detectAfter=1;val h=Handler();val c=VoiceClient();AudioRecord.onRead={if(it==2)c.idleSerial++}
  val origin=android.os.SystemClock.elapsedRealtime();val a=Capture(AssetManager(),h,c,{true}){};a.start()
  try {await{a.nativeProof.frames>=640};Thread.sleep(50);h.drain();assertEquals(2,c.wakes.size);assertTrue("first fed sample at start+320/16ms; conservative bridge bound",c.wakes[1]+1+CaptureClockBridge.LIMIT_MS in (origin+320/16-4)..(origin+320/16))}finally{a.close();h.drain()}
 }

 @Test fun slowRearmCannotResetLedgerOrHideNativeLoss(){
  AudioRecord.reset(3);SherpaWake.detectAfter=1
  AbsoluteWake.rearmHook={android.os.SystemClock.manualNow+=1399}
  val h=Handler();val c=VoiceClient();var errors=0
  AudioRecord.onRead={if(it==2)c.idleSerial++}
  val cap=Capture(AssetManager(),h,c,{true}){errors++};cap.start()
  try{await{cap.nativeProof.released};h.drain();assertTrue(errors>0);assertEquals(1,c.wakes.size)}
  finally{cap.close();h.drain();AbsoluteWake.rearmHook={}}
 }
 @Test fun cancelledInFlightRearmKeepsRecorderLeaseUntilWorkerEnds(){
  AudioRecord.reset(3);SherpaWake.detectAfter=1
  val entered=CountDownLatch(1);val release=CountDownLatch(1)
  AbsoluteWake.rearmHook={entered.countDown();release.await()}
  val h=Handler();val c=VoiceClient();AudioRecord.onRead={if(it==2)c.idleSerial++}
  val cap=Capture(AssetManager(),h,c,{true}){};cap.start()
  val second=Capture(AssetManager(),h,VoiceClient(),{true}){}
  try{assertTrue(entered.await(2,java.util.concurrent.TimeUnit.SECONDS));cap.close()
   second.start();assertEquals(1,AudioRecord.made.get());assertEquals(0,AudioRecord.active.get())
   release.countDown();cap.close();h.drain();assertTrue(cap.nativeProof.released);assertTrue(c.wakes.isEmpty())
  }finally{release.countDown();cap.close();second.close();h.drain();AbsoluteWake.rearmHook={}}
 }

 @Test fun childAndManagementNeverOwnNativeRecorderTogether(){AudioRecord.reset(1);SherpaWake.detectAfter=100
  val h=Handler();val m=ManagementCapture(AssetManager(),h,{true},{},{})
  val c=Capture(AssetManager(),h,VoiceClient(),{true}){}
  m.start();try{await{AudioRecord.active.get()==1};runCatching{c.start()};Thread.sleep(100);assertTrue(AudioRecord.maximum.get()<=1)}finally{m.close();c.close();h.drain()}
 }
 @Test fun cancelStopsNativeBeforeBlockedModelDisposal(){AudioRecord.reset(1);SherpaWake.detectAfter=100
  val h=Handler();val block=CountDownLatch(1);SherpaWake.blockClose=block
  val c=Capture(AssetManager(),h,VoiceClient(),{true}){};c.start()
  try{await{AudioRecord.active.get()==1};c.close();assertEquals(0,AudioRecord.active.get())}
  finally{SherpaWake.blockClose=null;block.countDown();c.close();h.drain()}
 }
}
