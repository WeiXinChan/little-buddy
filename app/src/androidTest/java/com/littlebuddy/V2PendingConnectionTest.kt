package com.littlebuddy
import android.content.Intent
import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Test
import org.junit.Assert.*
import okhttp3.*
import okio.ByteString
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
class V2PendingConnectionTest {
 private val i get()=InstrumentationRegistry.getInstrumentation()
 private fun await(message:String,test:()->Boolean){val end=SystemClock.elapsedRealtime()+15000;while(!test() && SystemClock.elapsedRealtime()<end)Thread.sleep(20);assertTrue(message,test())}
 private fun runCase(home:Boolean){
  val a=i.startActivitySync(Intent(i.targetContext,V2VoiceActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as V2VoiceActivity
  val dispose=CountDownLatch(1);val release=CountDownLatch(1);val connects=AtomicInteger()
  try {
   await("initial local real READ"){a.immediateRecorder().recording && a.immediateRecorder().frames>0}
   a.beforeCaptureDispose={dispose.countDown();release.await(6,TimeUnit.SECONDS)}
   a.transportOverride={request,_ ->connects.incrementAndGet();object:WebSocket{override fun request()=request;override fun queueSize()=0L;override fun send(text:String)=true;override fun send(bytes:ByteString)=true;override fun close(code:Int,reason:String?)=true;override fun cancel(){}}}
   i.runOnMainSync{a.startVoice("wss://localhost:1/v2/voice","SyntheticOnly".repeat(4))}
   assertTrue(dispose.await(5,TimeUnit.SECONDS));Thread.sleep(3317)
   assertEquals("no connect while old worker holds ownership",0,connects.get())
   if(home)i.uiAutomation.executeShellCommand("input keyevent KEYCODE_HOME").use{java.io.FileInputStream(it.fileDescriptor).readBytes()}
   if(home)await("actual HOME pause"){!a.resumed && !a.hasWindowFocus()}
   release.countDown()
   if(home){await("old native released and worker complete"){a.immediateRecorder().released && a.captureWorkerDone};assertEquals(0,connects.get())}
   else {await("pending request resumed after real disposal"){connects.get()==1 && a.immediateRecorder().recording && a.immediateRecorder().frames>0};Thread.sleep(100);assertEquals("exactly one restored connection",1,connects.get())}
  }finally{release.countDown();a.beforeCaptureDispose={};i.runOnMainSync{a.finish()};await("lease naturally returned after fixture"){a.immediateRecorder().released && a.captureWorkerDone}}
 }
 @Test fun completedDisposalRestoresCurrentIntentOnceAfter3317ms()=runCase(false)
 @Test fun homeRevokesIntentBeforeLateDisposal()=runCase(true)
}
