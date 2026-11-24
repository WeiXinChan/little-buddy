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
 /** Cold installs must prepare evidence before any owner barrier or file write. */
 fun evidenceDirectory():File {
  val root=i.targetContext.filesDir
  check(root.mkdirs() || root.isDirectory){"target files directory unavailable"}
  check(root.canWrite()){"target files directory not writable"}
  val directory=File(root,"m06")
  check(directory.mkdirs() || directory.isDirectory){"m06 evidence path is not a directory"}
  check(directory.canWrite()){"m06 evidence directory not writable"}
  return directory
 }
 fun launch():V2VoiceActivity {
  i.runOnMainSync{i.targetContext.startActivity(Intent(i.targetContext,V2VoiceActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))}
  var last:V2VoiceActivity?=null
  val end=SystemClock.elapsedRealtime()+15000
  while(SystemClock.elapsedRealtime()<end){var a:V2VoiceActivity?=null;i.runOnMainSync{a=ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED).filterIsInstance<V2VoiceActivity>().singleOrNull()};if(a!=null)last=a;if(a?.hasWindowFocus()==true)return a!!;Thread.sleep(20)}
  val failure=IllegalStateException("real resumed/focused Host not available; no UI idle dependency")
  try{snapshot(last,"launch-first")}catch(e:Throwable){failure.addSuppressed(e)}
  last?.let{a->try{finish(a)}catch(e:Throwable){failure.addSuppressed(e)}}
  throw failure
 }
 /** Actual global observations do not require any resumed Host. No readBytes(). */
 private fun shellEvidence(command:String,target:File,limit:Int):String {
  val end=SystemClock.elapsedRealtime()+3000
  var total=0;var eof=false
  // Target toybox timeout bounds the producer; poll/nonblocking read bounds our consumer.
  i.uiAutomation.executeShellCommand("timeout 2s $command").use{pipe->
   val fd=pipe.fileDescriptor
   android.system.Os.fcntlInt(fd,android.system.OsConstants.F_SETFL,
       android.system.Os.fcntlInt(fd,android.system.OsConstants.F_GETFL,0) or android.system.OsConstants.O_NONBLOCK)
   val poll=android.system.StructPollfd().apply{this.fd=fd;events=(android.system.OsConstants.POLLIN or android.system.OsConstants.POLLHUP or android.system.OsConstants.POLLERR).toShort()}
   target.outputStream().use{out->
    val buffer=ByteArray(8192)
    while(total<limit && SystemClock.elapsedRealtime()<end){
     val remaining=(end-SystemClock.elapsedRealtime()).coerceIn(1,250).toInt()
     if(android.system.Os.poll(arrayOf(poll),remaining)==0)continue
     val n=try{android.system.Os.read(fd,buffer,0,minOf(buffer.size,limit-total))}catch(e:android.system.ErrnoException){if(e.errno==android.system.OsConstants.EAGAIN || e.errno==android.system.OsConstants.EINTR)continue else throw e}
     if(n<=0){eof=true;break};out.write(buffer,0,n);total+=n
    }
   }
  }
  return "bytes=$total eof=$eof capped=${total==limit} timeout=${!eof && SystemClock.elapsedRealtime()>=end}"
 }
 fun snapshot(a:V2VoiceActivity?,name:String){
  val dir=evidenceDirectory()
  val status=dir.resolve("$name-evidence-status.txt")
  status.writeText("host=${a?.let{System.identityHashCode(it)}} startedMs=${SystemClock.elapsedRealtime()}\n")
  // Each independent query preserves progress/errors even if another observation fails.
  fun collect(label:String,block:()->String){
   status.appendText("begin=$label ms=${SystemClock.elapsedRealtime()}\n")
   try{status.appendText("end=$label ${block()}\n")}catch(e:Exception){status.appendText("error=$label class=${e.javaClass.simpleName}\n")}
  }
  if(a!=null){
   collect("host"){
    dir.resolve("$name-timeline.json").writeText(a.timelineJson())
    dir.resolve("$name-worker.txt").writeText(a.captureWorkerEvidence())
    val latch=CountDownLatch(1);a.observeDiagnostics{dir.resolve("$name-diagnostics.txt").writeText("host=${System.identityHashCode(a)} windowToken=${a.window.decorView.windowToken}\n$it");latch.countDown()}
    "ownerResponded=${latch.await(2,TimeUnit.SECONDS)}"
   }
  }
  for((suffix,command) in listOf("window" to "dumpsys window windows","top" to "dumpsys activity activities","keyguard" to "dumpsys window policy","audio" to "dumpsys audio")){
   collect(suffix){shellEvidence(command,dir.resolve("$name-$suffix.txt"),131072)}
  }
  collect("screenshot"){
   val partial=dir.resolve("$name-failure.png.partial")
   val result=shellEvidence("screencap -p",partial,8*1024*1024)
   if(result.contains("eof=true") && !result.contains("capped=true")){
    java.io.RandomAccessFile(partial,"r").use{png->
     check(png.length()>=20){"screencap too short"}
     val signature=ByteArray(8);png.readFully(signature)
     check(signature.contentEquals(byteArrayOf(-119,80,78,71,13,10,26,10))){"screencap PNG signature"}
     val endChunk=ByteArray(12);png.seek(png.length()-12);png.readFully(endChunk)
     check(endChunk.contentEquals(byteArrayOf(0,0,0,0,73,69,78,68,-82,66,96,-126))){"screencap incomplete PNG"}
    }
    check(partial.renameTo(dir.resolve("$name-failure.png"))){"screenshot rename"}
   }
   result
  }
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
