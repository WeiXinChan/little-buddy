package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
import android.media.AudioRecord
import android.os.Handler
import android.content.res.AssetManager
import com.littlebuddy.SherpaWake
import com.littlebuddy.v2.parent.PinDiagnostic
import com.littlebuddy.v2.parent.ConfigurationEventBudget
class RuntimeCaptureFailureTest {
 private fun run(reset:Boolean) {
  AudioRecord.reset(1050);SherpaWake.detectAfter=1;AbsoluteWake.initializeHook={};AbsoluteWake.rearmHook={}
  val h=Handler();val client=object:CaptureSessionPort {
   override val idleSerial=0L
   @Volatile override var inputSerial=0L
   override fun wake(boundary:WakeBoundary){}
   override fun frame(pcm:ShortArray,speech:Boolean,capturedAt:Long){pcm.fill(0)}
   override fun quiet(){}
   override fun stage(batch:List<ShortArray>,speech:Boolean,capturedAt:Long):Boolean {batch.forEach{it.fill(0)};return true}
  };var failures=0
  val events=java.util.concurrent.CopyOnWriteArrayList<PinDiagnostic.RuntimeEvent>()
  PinDiagnostic.installRuntime{events+=it}
  AudioRecord.onRead={if(reset && it==600)client.inputSerial++;Thread.sleep(1)}
  val cap=Capture(AssetManager(),h,client,{true}){failures++};cap.start()
  try {
   val end=System.nanoTime()+5_000_000_000
   while(System.nanoTime()<end && !cap.nativeProof.released && cap.nativeProof.frames<1050*320L){h.drain();Thread.sleep(1)}
   h.drain()
   if(reset){assertEquals(0,failures);assertEquals(1050*320L,cap.nativeProof.frames);assertTrue(events.none{it.stage==PinDiagnostic.RuntimeStage.CAPTURE_FAILURE})}
   else {
    val joinEnd=System.nanoTime()+2_000_000_000
    while(events.none{it.stage==PinDiagnostic.RuntimeStage.WORKER_JOINED} && System.nanoTime()<joinEnd){h.drain();Thread.sleep(1)}
    h.drain();assertTrue(events.any{it.stage==PinDiagnostic.RuntimeStage.WORKER_JOINED})
    assertTrue(cap.nativeProof.released);assertEquals("existing catch + finally owner failure notifications",2,failures);assertNull(cap.lastClockFailure)
    val e=events.single{it.stage==PinDiagnostic.RuntimeStage.CAPTURE_FAILURE}
    assertEquals(CapturePredicate.INPUT_CAPACITY,e.capturePredicate);assertNull(e.clockReason)
    assertTrue(e.uploadSamples>=300000);assertEquals(0L,e.inputSerial);assertEquals(0L,e.sealedSerial)
    println("RUNTIME_FAILURE predicate=${e.capturePredicate} uploaded=${e.uploadSamples} native=${e.nativeReturnedSamples} clock=${e.clockReason}")
   }
  }finally{cap.close();h.drain();PinDiagnostic.installRuntime(null);assertTrue(ProcessRecorders.released())}
 }
 @Test fun uninterruptedVoicedInputWithoutEndpointFailsCapacityNotClock()=run(false)
 @Test fun completedInputSerialResetsCounterWithoutExtendingClock()=run(true)
 @Test fun ordinaryAndCriticalFloodCannotSpendFailureReservation(){for(config in listOf(false,true)){
  val b=ConfigurationEventBudget(config);var n=0
  repeat(1000){if(b.general())n++;if(b.configuration())n++;if(b.critical())n++;if(b.operation())n++;if(b.phase())n++}
  assertEquals(254,n);assertTrue(b.failure());assertTrue(b.failure());assertFalse(b.failure())
 }}
}
