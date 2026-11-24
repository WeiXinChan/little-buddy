package com.littlebuddy
import android.content.Intent
import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import com.littlebuddy.v2.Capture
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
internal object V2HostFixture {
 private val i get()=InstrumentationRegistry.getInstrumentation()
 fun launch():V2VoiceActivity {
  i.runOnMainSync{i.targetContext.startActivity(Intent(i.targetContext,V2VoiceActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))}
  var last:V2VoiceActivity?=null
  val end=SystemClock.elapsedRealtime()+15000
  while(SystemClock.elapsedRealtime()<end){var a:V2VoiceActivity?=null;i.runOnMainSync{a=ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED).filterIsInstance<V2VoiceActivity>().singleOrNull()};if(a!=null)last=a;if(a?.hasWindowFocus()==true)return a!!;Thread.sleep(20)}
  val failure=IllegalStateException("real resumed/focused Host not available; no UI idle dependency")
  last?.let{a->try{snapshot(a,"launch-first")}catch(e:Throwable){failure.addSuppressed(e)};try{finish(a)}catch(e:Throwable){failure.addSuppressed(e)}}
  throw failure
 }
 fun snapshot(a:V2VoiceActivity,name:String){
  val dir=File(i.targetContext.filesDir,"m06").apply{mkdirs()}
  dir.resolve("$name-timeline.json").writeText(a.timelineJson())
  dir.resolve("$name-worker.txt").writeText(a.captureWorkerEvidence())
  val latch=CountDownLatch(1);a.observeDiagnostics{dir.resolve("$name-diagnostics.txt").writeText("host=${System.identityHashCode(a)} windowToken=${a.window.decorView.windowToken}\n$it");latch.countDown()};latch.await(2,TimeUnit.SECONDS)
  for((suffix,command) in listOf("window" to "dumpsys window windows","top" to "dumpsys activity activities","keyguard" to "dumpsys window policy")){
   i.uiAutomation.executeShellCommand(command).use{fd->java.io.FileInputStream(fd.fileDescriptor).use{dir.resolve("$name-$suffix.txt").writeBytes(it.readBytes().take(131072).toByteArray())}}
  }
  i.uiAutomation.takeScreenshot()?.let{b->dir.resolve("$name-failure.png").outputStream().use{b.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it)};b.recycle()}
 }
 fun finish(a:V2VoiceActivity){
  val acquired=a.captureHasResources()
  i.runOnMainSync{a.finish()}
  val end=SystemClock.elapsedRealtime()+15000
  fun done():Boolean {val p=a.immediateRecorder();return !p.recording && a.captureWorkerDone && Capture.leaseAvailable && (!(acquired || p.session!=null) || p.released && (!p.started || p.stopped))}
  while(!done() && SystemClock.elapsedRealtime()<end)Thread.sleep(20)
  val frames=a.immediateRecorder().frames;Thread.sleep(100);check(frames==a.immediateRecorder().frames){"frames advanced after cleanup"}
  check(done()){"Host cleanup: acquired=$acquired ${a.captureWorkerEvidence()}"}
 }
}
