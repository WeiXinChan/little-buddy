package com.littlebuddy
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import okhttp3.*
import okio.ByteString
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import com.littlebuddy.v2.*
import java.util.concurrent.atomic.AtomicInteger
import java.io.File

/** Host paplay -> controlled AVD mic -> real AudioRecord/KWS -> production owner.
 * Network adapter is synthetic; no private receive, fixed recognizer or cloud LLM.
 */
class V2MicrophoneCommandTest {
 private val inst get()=InstrumentationRegistry.getInstrumentation()
 private class Wire(val request: Request,val listener: WebSocketListener):WebSocket {
  val inputs=AtomicInteger();val wakes=AtomicInteger();var player="";var epoch=0L;var revision=0L
  override fun request()=request
  override fun queueSize()=0L
  override fun send(text:String):Boolean {
   val e=JSONObject(text);epoch=e.getLong("epoch")
   when(e.getString("type")) {
    "input" -> inputs.incrementAndGet()
    "wake" -> wakes.incrementAndGet()
    "advance" -> revision=e.getLong("revision")
    "bind" -> {player=e.getString("player");emit("bound","player" to player,"identity" to JSONObject(),"stream" to 1)
     emit("audio","player" to player,"stream" to 1,"segment" to "synthetic","start" to 0,"end" to 2400,"pcm" to android.util.Base64.encodeToString(ByteArray(4800),2))}
   };return true
  }
  fun emit(kind:String,vararg fields:Pair<String,Any>) {val o=JSONObject().put("v",2).put("epoch",epoch).put("type",kind);fields.forEach{o.put(it.first,it.second)};listener.onMessage(this,o.toString())}
  override fun send(bytes:ByteString)=false
  override fun close(code:Int,reason:String?)=true
  override fun cancel(){}
 }
 private var diagnosticHost: V2VoiceActivity?=null
 private fun await(name:String,condition:()->Boolean) {
  val end=SystemClock.elapsedRealtime()+12000
  while(!condition() && SystemClock.elapsedRealtime()<end)Thread.sleep(20)
  if(!condition()) {
   val dir=File(inst.targetContext.filesDir,"m06").apply{mkdirs()}
   val host=diagnosticHost
   if(host!=null){dir.resolve("microphone-timeline.json").writeText(host.timelineJson());val latch=java.util.concurrent.CountDownLatch(1);host.observeDiagnostics{dir.resolve("microphone-diagnostics.txt").writeText(it);latch.countDown()};latch.await(2,java.util.concurrent.TimeUnit.SECONDS)}
  }
  assertTrue(name,condition())
 }
 private var syntheticProbe:SyntheticInputProbe?=null
 private val requests=mutableMapOf<String,JSONObject>()
 private fun completed(name:String):Boolean {
  val q=requests[name] ?: return false
  val f=File(inst.targetContext.filesDir,"m06-${q.getString("nonce")}.json")
  if(!f.isFile)return false
  return try{val r=JSONObject(f.readText());r.getString("nonce")==q.getString("nonce") && r.getString("sha256")==q.getString("sha256") && r.getString("state")=="completed" && r.getInt("playback_exit")==0}catch(_:Exception){false}
 }
 private fun play(name:String) {
  val root=inst.targetContext.filesDir
  check(root.mkdirs() || root.isDirectory)
  check(root.canWrite())
  val bytes=(if(name.startsWith("prod_"))inst.targetContext.assets else inst.context.assets).open(if(name.startsWith("prod_"))"management/${name.removePrefix("prod_")}.wav" else if(name.startsWith("v2_"))"m06-protocol-v2/${name.removePrefix("v2_")}.wav" else "m06-commands/$name.wav").use{it.readBytes()}
  val hash=java.security.MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02x".format(it)}
  val q=JSONObject().put("name",name).put("sha256",hash).put("nonce",java.util.UUID.randomUUID().toString()).put("root",root.canonicalPath).put("package",inst.targetContext.packageName).put("user",android.os.Process.myUid()/100000)
  if(name=="enter" && syntheticProbe==null && diagnosticHost?.syntheticProbeAllowed()==true)syntheticProbe=SyntheticInputProbe(checkNotNull(diagnosticHost),q.getString("nonce"),bytes,hash)
  requests[name]=q
  File(root,"m06").mkdirs()
  File(root,"m06/handshake-root.json").writeText(q.toString())
  inst.sendStatus(30,Bundle().apply{putString("m06_request",q.toString())})
 }
 @Test fun actualMicrophoneManagementAndNegativeCommands() {
  val ctx=inst.targetContext
  check(ctx.filesDir.mkdirs() || ctx.filesDir.isDirectory)
  check(ctx.filesDir.canWrite())
  val activity=V2HostFixture.launch()
  activity.syntheticCaptureDiagnostics=true
  diagnosticHost=activity
  lateinit var wire:Wire
  var primary:Throwable?=null
  try {
   await("focused host"){activity.hasWindowFocus() && activity.resumed}
   inst.runOnMainSync {
    activity.transportOverride={request,listener -> Wire(request,listener).also {wire=it;listener.onOpen(it,Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(101).message("synthetic").build())}}
    activity.startVoice("wss://localhost:1/v2/voice","SyntheticOnly".repeat(4))
   }
   await("production Capture real READ"){activity.immediateRecorder().frames>0 && activity.immediateRecorder().recording}
   activity.withVoice{it.wake();wire.emit("open","revision" to wire.revision)}
   await("native output bound"){wire.player.isNotEmpty()}
   val ready=java.util.concurrent.CountDownLatch(1)
   activity.observeNative{if(it.player.observedHead>0)ready.countDown()}
   // head is asynchronous, keep observing without replacing native progress.
   await("native output really progressed"){var head=false;val l=java.util.concurrent.CountDownLatch(1);activity.observeNative{head=it.player.observedHead>0;l.countDown()};l.await(1,java.util.concurrent.TimeUnit.SECONDS);head}
   play("enter")
   await("authorized enter fixture playback completed"){completed("enter")}
   Thread.sleep(1600);syntheticProbe?.freeze()
   inst.runOnMainSync {activity.pictureResolver={Bitmap.createBitmap(40,40,Bitmap.Config.ARGB_8888).apply{eraseColor(Color.GREEN)}};activity.revealImage("synthetic",1)}
   await("AudioRecord/KWS entered management"){activity.isManaging}
   assertFalse(activity.showingImage)
   var released=false;val release=java.util.concurrent.CountDownLatch(1)
   activity.observeNative{released=it.player.binding==null && it.player.stop==StopResult(true,true);release.countDown()};assertTrue(release.await(2,java.util.concurrent.TimeUnit.SECONDS));assertTrue(released)
   val before=wire.inputs.get();wire.emit("reveal","effect" to "synthetic","topic" to 5);wire.emit("audio","player" to wire.player,"stream" to 1,"segment" to "late","start" to 2400,"end" to 2640,"pcm" to android.util.Base64.encodeToString(ByteArray(480),2))
   for(name in listOf("cancel_negative","cancel_discussion","negative_pause_cancel_1.6","cancel_continued_discussion")) {
    play(name);await("audio playback completed: $name"){completed(name)};Thread.sleep(1200)
    assertTrue("negative command must stay managed: $name",activity.isManaging);assertEquals(before,wire.inputs.get());assertFalse(activity.showingImage)
   }
   play("v2_confirm_exit_short");await("pre-prompt confirmation really played"){completed("v2_confirm_exit_short")};Thread.sleep(1600)
   assertTrue("confirmation without a newly published window cannot exit",activity.isManaging)
   fun events(name:String):Int {val a=org.json.JSONArray(activity.timelineJson());return (0 until a.length()).count{a.getJSONObject(it).getString("event")==name}}
   val beforeBarrier=events("CONFIRM_NATIVE_BARRIER");val beforePrompt=events("LOCAL_PROMPT_NATIVE_COMPLETE");val serial=activity.managementPromptSerial
   play("cancel");await("new prompt drawn"){activity.managementPromptSerial>serial}
   play("prod_confirm_prompt");await("captured prompt feedback fixture completed"){completed("prod_confirm_prompt")}
   await("real prompt native completion before new capture barrier"){events("LOCAL_PROMPT_NATIVE_COMPLETE")>beforePrompt && events("CONFIRM_NATIVE_BARRIER")>beforeBarrier}
   assertTrue("prompt feedback must not confirm itself",activity.isManaging);assertEquals(before,wire.inputs.get())
   play("v2_confirm_exit_short");await("real post-audible-prompt new confirmation returns WAKE"){!activity.isManaging && activity.currentMood==EyeMood.WAKE};assertEquals(before,wire.inputs.get())
   play("exit");await("outside exit fixture done"){completed("exit")};assertFalse(activity.isManaging)
   play("enter_polite");await("fresh enter through real mic"){activity.isManaging}
   play("exit");await("real exit returns WAKE"){!activity.isManaging && activity.currentMood==EyeMood.WAKE};assertEquals(before,wire.inputs.get())
   val wakes=wire.wakes.get();play("wake");await("next actual wake only"){wire.wakes.get()>wakes}
   val old=activity.immediateRecorder();val uploads=wire.inputs.get()
   inst.uiAutomation.executeShellCommand("input keyevent KEYCODE_HOME").use{java.io.FileInputStream(it.fileDescriptor).readBytes()}
   await("explicit session HOME paused/focus lost"){!activity.resumed && !activity.hasWindowFocus()}
   await("explicit session HOME native released and worker done"){val p=activity.immediateRecorder();p.session==old.session && p.stopped && p.released && !p.recording && activity.captureWorkerDone}
   val stoppedFrames=activity.immediateRecorder().frames;Thread.sleep(100);assertEquals(stoppedFrames,activity.immediateRecorder().frames)
   assertSame(activity,V2HostFixture.launch())
   await("explicit session returns new local KWS READ"){val p=activity.immediateRecorder();activity.resumed && activity.hasWindowFocus() && p.session!=old.session && p.recording && p.frames>0}
   assertEquals("return must not resume old cloud upload",uploads,wire.inputs.get())
   File(ctx.filesDir,"m06").mkdirs();File(ctx.filesDir,"m06/microphone-management.json").writeText(JSONObject().put("real_AudioRecord",true).put("KWS",true).put("network_adapter","synthetic WebSocket; cloud ASR/LLM not tested").put("managed_input_delta",wire.inputs.get()-before).put("timeline",org.json.JSONArray(activity.timelineJson())).toString(2))
  } catch(t:Throwable){primary=t;try{V2HostFixture.snapshot(activity,"microphone-first")}catch(e:Throwable){t.addSuppressed(e)};throw t
  } finally {
   var cleanup:Throwable?=null
   try{syntheticProbe?.saveAndReplay()}catch(e:Throwable){cleanup=e}
   try{V2HostFixture.finish(activity)}catch(e:Throwable){if(cleanup!=null)cleanup.addSuppressed(e) else cleanup=e}
   if(cleanup!=null){if(primary!=null)primary.addSuppressed(cleanup)else throw cleanup}
  }
 }
}
