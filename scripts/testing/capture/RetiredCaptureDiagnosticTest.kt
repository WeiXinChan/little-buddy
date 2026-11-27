package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
import android.media.AudioRecord
import android.content.res.AssetManager
import android.os.Handler
import com.littlebuddy.SherpaWake
import com.littlebuddy.v2.parent.PinDiagnostic
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

class RetiredCaptureDiagnosticTest {
 @Test fun callerCancelDuringTimestampKeepsTypedOldScopeAndNeverPostsFailureOrPcm(){
  AudioRecord.reset(6);SherpaWake.detectAfter=100
  val owner=Handler();val client=VoiceClient();var uiFailures=0
  val seen=AtomicReference<CaptureClockFailure?>();val emitted=CountDownLatch(1)
  val scope=PinDiagnostic.Scope(3,2,7)
  val capture=Capture(AssetManager(),owner,client,{true},diagnosticScope=scope){uiFailures++}
  CaptureClockDiagnostic.install{error->if(error.reason==CaptureClockReason.TIMESTAMP_STALE){seen.set(error);emitted.countDown()}}
  AudioRecord.onRead={n->if(n==3)AudioRecord.beforeTimestamp={
    AudioRecord.beforeTimestamp={};capture.requestCancel();android.os.SystemClock.manualNow+=113
  }}
  try {
   capture.start();assertTrue(emitted.await(3,TimeUnit.SECONDS))
   capture.close();owner.drain()
   val error=checkNotNull(seen.get());assertEquals(CaptureClockReason.TIMESTAMP_STALE,error.reason)
   assertTrue(error.context!!.cancelled);assertTrue(error.context!!.stopRequested)
   assertEquals(3L,error.context!!.activity);assertEquals(2L,error.context!!.transport);assertEquals(7L,error.context!!.capture)
   assertEquals(CaptureReadStep.POST_READ,error.context!!.step);assertEquals(0,uiFailures)
   assertTrue(client.received.isEmpty());assertTrue(client.wakes.isEmpty());assertEquals(0,AudioRecord.active.get())
  } finally {AudioRecord.beforeTimestamp={};capture.close();owner.drain();CaptureClockDiagnostic.install(null)}
 }
}
