package com.littlebuddy
import android.content.Intent
import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import com.littlebuddy.v2.Capture
import okhttp3.*
import okio.ByteString
import org.junit.Test
import org.junit.Assert.*
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
class V2CompletionLeaseTest {
 private val i get()=InstrumentationRegistry.getInstrumentation()
 private fun await(message:String,f:()->Boolean){val until=SystemClock.elapsedRealtime()+15000;while(!f() && SystemClock.elapsedRealtime()<until)Thread.sleep(20);assertTrue(message,f())}
 private fun runCase(explicit:Boolean){
  val a=V2HostFixture.launch()
  val joined=CountDownLatch(1);val allowReturn=CountDownLatch(1);val timeout=AtomicBoolean();val connects=AtomicInteger()
  var primary:Throwable?=null
  try {
   await("initial native READ"){a.immediateRecorder().recording && a.immediateRecorder().frames>0};val old=a.immediateRecorder().session
   a.beforeCaptureLeaseReturn={joined.countDown();if(!allowReturn.await(6,TimeUnit.SECONDS))timeout.set(true)}
   a.transportOverride={r,_ ->connects.incrementAndGet();object:WebSocket{override fun request()=r;override fun queueSize()=0L;override fun send(text:String)=true;override fun send(bytes:ByteString)=true;override fun close(code:Int,reason:String?)=true;override fun cancel(){}}}
   if(explicit)i.runOnMainSync{a.startVoice("wss://localhost:1/v2/voice","SyntheticOnly".repeat(4))}
   else i.uiAutomation.executeShellCommand("input keyevent KEYCODE_HOME").use{java.io.FileInputStream(it.fileDescriptor).readBytes()}
   assertTrue("worker joined before lease return barrier",joined.await(6,TimeUnit.SECONDS));assertTrue(a.immediateRecorder().released);assertFalse(Capture.leaseAvailable)
   if(!explicit)assertSame("restore same Host",a,V2HostFixture.launch())
   val observed=CountDownLatch(1);var evidence="";a.observeDiagnostics{evidence=it;observed.countDown()};assertTrue(observed.await(2,TimeUnit.SECONDS))
   assertTrue("old owner retained while completion paused: $evidence",evidence.contains("ownsLease=true"));assertEquals(old,a.immediateRecorder().session);assertEquals(0,connects.get());assertFalse(timeout.get())
   a.beforeCaptureLeaseReturn={};allowReturn.countDown()
   await("one new owner after natural lease return"){val p=a.immediateRecorder();p.session!=old && p.recording && p.frames>0}
   assertEquals(if(explicit)1 else 0,connects.get());Thread.sleep(100);assertEquals(if(explicit)1 else 0,connects.get())
  }catch(t:Throwable){primary=t;try{V2HostFixture.snapshot(a,"completion-first")}catch(e:Throwable){t.addSuppressed(e)};throw t
  }finally{a.beforeCaptureLeaseReturn={};allowReturn.countDown();try{V2HostFixture.finish(a)}catch(e:Throwable){if(primary!=null)primary.addSuppressed(e)else throw e}}
 }
 @Test fun stopThenLocalStartKeepsOwnerUntilCompletionReturnsLease()=runCase(false)
 @Test fun explicitIntentCannotBypassLeaseWhenWorkerAlreadyEnded()=runCase(true)
}
