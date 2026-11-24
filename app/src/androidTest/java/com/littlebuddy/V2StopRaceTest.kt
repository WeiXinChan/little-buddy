package com.littlebuddy
import android.content.Intent
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import com.littlebuddy.v2.*
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
class V2StopRaceTest {
 @Test fun blockedDecodeAndDisposalCannotKeepNativeRecording() {
  val inst=InstrumentationRegistry.getInstrumentation();val thread=HandlerThread("stop-race").apply{start()};val owner=Handler(thread.looper)
  val decode=CountDownLatch(1);val releaseDecode=CountDownLatch(1);val disposal=CountDownLatch(1);val releaseDisposal=CountDownLatch(1)
  val client=VoiceClient(owner,{}, {},{_,_->})
  val capture=Capture(inst.targetContext.assets,owner,client,{},hooks=CaptureHooks(
   {decode.countDown();check(releaseDecode.await(5,TimeUnit.SECONDS))},
   {disposal.countDown();check(releaseDisposal.await(5,TimeUnit.SECONDS))}))
  try {
   assertTrue("Capture.start lease acquisition phase=${capture.phase}",capture.start());assertTrue("real read reached decode barrier phase=${capture.phase} proof=${capture.nativeProof}",decode.await(15,TimeUnit.SECONDS))
   capture.requestStop();assertTrue(capture.nativeProof.stopped);assertFalse(capture.nativeProof.recording)
   capture.close();assertTrue(capture.quarantined)
   releaseDecode.countDown();assertTrue(disposal.await(3,TimeUnit.SECONDS))
   assertTrue("native release precedes blocked model disposal",capture.nativeProof.released)
   releaseDisposal.countDown()
   val deadline=SystemClock.elapsedRealtime()+2000
   while((!capture.workerDone || !capture.leaseReturned) && SystemClock.elapsedRealtime()<deadline)Thread.sleep(10)
   assertTrue(capture.workerDone);assertTrue("lease returns only after worker completion",capture.leaseReturned);assertFalse("pending disposal clears only when worker done",capture.quarantined)
  } finally {releaseDecode.countDown();releaseDisposal.countDown();capture.close();owner.post{client.close();thread.quitSafely()};thread.join(2000)}
 }
 @Test fun expiredAfterEligibilityDoesNotKillOwnerOrStartCapture() {
  val inst=InstrumentationRegistry.getInstrumentation()
  val activity=inst.startActivitySync(Intent(inst.targetContext,V2VoiceActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as V2VoiceActivity
  val passed=CountDownLatch(1);val consume=CountDownLatch(1);val alive=CountDownLatch(1)
  try {
   // Real window focus transitions while the production owner is held past eligibility.
   inst.runOnMainSync {activity.afterEligible={passed.countDown();check(consume.await(5,TimeUnit.SECONDS))}}
   lateinit var dialog: android.app.Dialog
   inst.runOnMainSync{dialog=android.app.Dialog(activity)}
   inst.runOnMainSync{dialog.show()};inst.waitForIdleSync();inst.runOnMainSync{dialog.dismiss()}
   assertTrue(passed.await(3,TimeUnit.SECONDS))
   inst.runOnMainSync {activity.startVoice("wss://localhost:1/v2/voice","SyntheticOnly".repeat(4))}
   inst.uiAutomation.executeShellCommand("input keyevent KEYCODE_HOME").use {java.io.FileInputStream(it.fileDescriptor).readBytes()}
   val deadline=SystemClock.elapsedRealtime()+2000
   while(activity.resumed && SystemClock.elapsedRealtime()<deadline)Thread.sleep(10)
   assertFalse(activity.resumed)
   consume.countDown()
   activity.observeDiagnostics{alive.countDown()}
   assertTrue("owner survives cancelled post-eligibility start",alive.await(3,TimeUnit.SECONDS))
   val pause=org.json.JSONArray(activity.timelineJson())
   assertTrue("queued explicit connect must be rejected",activity.timelineJson().contains("STALE_CONNECT_REJECTED"))
   var lastPause=0L
   for(i in 0 until pause.length())if(pause.getJSONObject(i).getString("event")=="LIFE_PAUSE")lastPause=pause.getJSONObject(i).getLong("ms")
   for(i in 0 until pause.length()) {val e=pause.getJSONObject(i);assertFalse(e.getString("event")=="NATIVE_START" && e.getLong("ms")>lastPause)}
  } finally {consume.countDown();inst.runOnMainSync{activity.afterEligible={};activity.finish()};val until=SystemClock.elapsedRealtime()+5000;while((!activity.immediateRecorder().released || !activity.captureWorkerDone) && SystemClock.elapsedRealtime()<until)Thread.sleep(20);assertTrue("Host native release before next test",activity.immediateRecorder().released && activity.captureWorkerDone)}
 }
}
