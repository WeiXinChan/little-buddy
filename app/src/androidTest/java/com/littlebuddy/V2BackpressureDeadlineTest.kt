package com.littlebuddy
import android.os.SystemClock
import com.littlebuddy.v2.*
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.json.JSONArray
import org.json.JSONObject
import okhttp3.*
import okio.ByteString
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
class V2BackpressureDeadlineTest {
 @Test fun foregroundEligibleOwnerStallStopsRealNativeWithoutOldReplay(){
  val i=InstrumentationRegistry.getInstrumentation();val a=V2HostFixture.launch();val release=CountDownLatch(1);val entered=CountDownLatch(1);val once=AtomicBoolean();val inputs=AtomicInteger();val dispatched=AtomicInteger();var started=0L;var primary:Throwable?=null
  fun await(name:String,f:()->Boolean){val end=SystemClock.elapsedRealtime()+15000;while(!f() && SystemClock.elapsedRealtime()<end)Thread.sleep(10);assertTrue(name,f())}
  try{
   await("initial actual local READ"){a.immediateRecorder().recording && a.immediateRecorder().frames>0}
   a.afterUploadDelivery={dispatched.incrementAndGet()}
   a.afterCaptureFirstRead={upload->if(once.compareAndSet(false,true)){started=SystemClock.elapsedRealtime();upload(List(50){ShortArray(320)});upload(listOf(ShortArray(320)))}}
   a.afterCaptureStart={entered.countDown();release.await(15,TimeUnit.SECONDS)}
   a.transportOverride={r,_->object:WebSocket{override fun request()=r;override fun queueSize()=0L;override fun send(text:String):Boolean{if(JSONObject(text).optString("type")=="input")inputs.incrementAndGet();return true};override fun send(bytes:ByteString)=false;override fun close(code:Int,reason:String?)=true;override fun cancel(){}}}
   i.runOnMainSync{a.startVoice("wss://localhost:1/v2/voice","SyntheticOnly".repeat(4))}
   assertTrue(entered.await(15,TimeUnit.SECONDS))
   fun interrupted():Long? {val events=JSONArray(a.timelineJson());return (0 until events.length()).map{events.getJSONObject(it)}.firstOrNull{it.getString("event")=="INPUT_INTERRUPTED"}?.getLong("ms")}
   await("production read must mark interruption"){interrupted()!=null};assertTrue(a.resumed && a.hasWindowFocus());assertTrue(interrupted()!!-started in 0..300)
   await("real native release while owner remains paused"){val p=a.immediateRecorder();p.started && p.stopped && p.released && !p.recording && a.captureWorkerDone}
   val frames=a.immediateRecorder().frames;Thread.sleep(100);assertEquals(frames,a.immediateRecorder().frames);assertEquals(0,inputs.get())
   a.afterCaptureStart={};a.afterCaptureFirstRead={};release.countDown()
   val settled=CountDownLatch(1);a.observeDiagnostics{settled.countDown()};assertTrue(settled.await(3,TimeUnit.SECONDS));assertEquals("no old queued input on recovery",0,inputs.get());assertEquals("no cancelled producer frames dispatched",0,dispatched.get())
  }catch(e:Throwable){primary=e;try{V2HostFixture.snapshot(a,"backpressure-deadline")}catch(extra:Throwable){e.addSuppressed(extra)};throw e
  }finally{a.afterCaptureStart={};a.afterCaptureFirstRead={};a.afterUploadDelivery={};release.countDown();try{V2HostFixture.finish(a)}catch(e:Throwable){if(primary!=null)primary.addSuppressed(e)else throw e}}
 }
}
