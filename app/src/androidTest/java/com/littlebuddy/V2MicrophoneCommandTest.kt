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
  val inputs=AtomicInteger();val wakes=AtomicInteger();@Volatile var player="";var epoch=0L;var revision=0L
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
 private val calibrationSource get()=InstrumentationRegistry.getArguments().getString("m06_source")
 private val calibrationNonce get()=InstrumentationRegistry.getArguments().getString("m06_nonce")
 private var gatesAccepted=false
 private var liveEnter=false
 private var initialSourceEvidence=JSONObject()
 private var initialSession:Int?=null
 private var diagnosticHost: V2VoiceActivity?=null
 private fun await(name:String,condition:()->Boolean) {
  val end=SystemClock.elapsedRealtime()+12000
  if(name=="authorized enter fixture playback completed" || name=="AudioRecord/KWS entered management")timing("AWAIT_DEADLINE_$name","enter",end)
  while(!condition() && SystemClock.elapsedRealtime()<end)Thread.sleep(20)
  if(!condition()) {
   val dir=V2HostFixture.evidenceDirectory()
   val host=diagnosticHost
   if(host!=null){dir.resolve("microphone-timeline.json").writeText(host.timelineJson());val latch=java.util.concurrent.CountDownLatch(1);host.observeDiagnostics{dir.resolve("microphone-diagnostics.txt").writeText(it);latch.countDown()};latch.await(2,java.util.concurrent.TimeUnit.SECONDS)}
  }
  assertTrue(name,condition())
 }
 private var syntheticProbe:SyntheticInputProbe?=null
 private val requests=mutableMapOf<String,JSONObject>()
 private val playTiming=org.json.JSONArray()
 private fun timing(phase:String,name:String,deadline:Long?=null){
  val q=requests[name] ?: return
  val p=diagnosticHost?.immediateRecorder()
  playTiming.put(JSONObject().put("phase",phase).put("name",name).put("nonce",q.getString("nonce")).put("elapsed_ms",SystemClock.elapsedRealtime()).put("monotonic_ns",System.nanoTime()).put("native_session",p?.session).put("native_read_end_frame",p?.frames).put("deadline_elapsed_ms",deadline))
  V2HostFixture.evidenceDirectory().resolve("microphone-play-timing.json").writeText(playTiming.toString(2))
 }
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
  val q=JSONObject().put("name",name).put("sha256",hash).put("nonce",if(name=="enter" && calibrationNonce!=null)calibrationNonce else java.util.UUID.randomUUID().toString()).put("root",root.canonicalPath).put("package",inst.targetContext.packageName).put("user",android.os.Process.myUid()/100000)
  if(name=="enter" && syntheticProbe==null && diagnosticHost?.syntheticProbeAllowed()==true)syntheticProbe=SyntheticInputProbe(checkNotNull(diagnosticHost),q.getString("nonce"),bytes,hash)
  val proof=diagnosticHost?.immediateRecorder()
  q.put("request_guest_elapsed_ms",SystemClock.elapsedRealtime()).put("request_guest_monotonic_ns",System.nanoTime()).put("request_native_session",proof?.session).put("request_native_read_end_frame",proof?.frames).put("source_configuration",diagnosticHost?.captureSourceEvidence())
  requests[name]=q
  val evidence=V2HostFixture.evidenceDirectory()
  timing("BEFORE_SEND_STATUS",name)
  evidence.resolve("handshake-root.json").writeText(q.toString())
  inst.sendStatus(30,Bundle().apply{putString("m06_request",q.toString())})
 }
 @Test fun actualMicrophoneManagementAndNegativeCommands() {
  val ctx=inst.targetContext
  V2HostFixture.evidenceDirectory()
  val activity=V2HostFixture.launch()
  activity.syntheticCaptureDiagnostics=true
  diagnosticHost=activity
  lateinit var wire:Wire
  val wireReady=java.util.concurrent.atomic.AtomicReference<Wire?>()
  val ownerPaused=java.util.concurrent.CountDownLatch(1);val ownerResume=java.util.concurrent.CountDownLatch(1)
  var primary:Throwable?=null
  try {
   await("focused host"){activity.hasWindowFocus() && activity.resumed}
   if(calibrationSource!=null)await("pre-calibration local native READ"){activity.immediateRecorder().frames>0 && activity.immediateRecorder().recording}
   val previousSession=activity.captureReadSnapshot()?.session
   V2HostFixture.evidenceDirectory() // Must succeed before pausing the owner.
   if(calibrationSource!=null)activity.afterEligible={ownerPaused.countDown();check(ownerResume.await(3,java.util.concurrent.TimeUnit.SECONDS))}
   inst.runOnMainSync {
    if(calibrationSource!=null){
     val selected=when(calibrationSource){"7"->CaptureInput.COMMUNICATION;"6"->CaptureInput.RECOGNITION;else->error("unsupported calibration source")}
     val fixture=inst.context.assets.open("m06-commands/enter.wav").use{it.readBytes()}
     val sha=java.security.MessageDigest.getInstance("SHA-256").digest(fixture).joinToString(""){"%02x".format(it)}
     check(sha==SyntheticSourcePermit.ENTER_SHA)
     activity.selectSyntheticSource(selected,checkNotNull(calibrationNonce),sha)
    }
    activity.transportOverride={request,listener -> Wire(request,listener).also {wire=it;wireReady.set(it);listener.onOpen(it,Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(101).message("synthetic").build())}}
    activity.startVoice("wss://localhost:1/v2/voice","SyntheticOnly".repeat(4))
   }
   if(calibrationSource!=null){
    try{
     assertTrue("owner paused before consuming new request",ownerPaused.await(3,java.util.concurrent.TimeUnit.SECONDS))
     val old=checkNotNull(activity.captureReadSnapshot());assertTrue("old local really remains READ",old.reading)
     val expected=if(calibrationSource=="6")CaptureInput.RECOGNITION else CaptureInput.COMMUNICATION
     assertFalse("old READ cannot satisfy new nonce/source",old.readyFor(checkNotNull(calibrationNonce),expected))
     V2HostFixture.evidenceDirectory().resolve("old-read-negative-${calibrationNonce}.json").writeText(activity.captureSourceEvidence().put("expected_nonce",calibrationNonce).put("ready",false).toString(2))
    }finally{activity.afterEligible={};ownerResume.countDown()}
   }
   await("production Capture real READ"){
    val p=activity.captureReadSnapshot()
    wireReady.get()!=null && p!=null && (if(calibrationSource!=null)p.readyFor(checkNotNull(calibrationNonce),if(calibrationSource=="6")CaptureInput.RECOGNITION else CaptureInput.COMMUNICATION) else p.reading && p.session!=previousSession)
   }
   initialSourceEvidence=activity.captureSourceEvidence();initialSession=initialSourceEvidence.getInt("session")
   if(calibrationSource!=null){
    val evidence=initialSourceEvidence
    if(evidence.optInt("requested")!=calibrationSource!!.toInt() || evidence.optInt("actual")!=calibrationSource!!.toInt())gatesAccepted=false
    assertEquals(calibrationSource!!.toInt(),evidence.getInt("requested"));assertEquals(calibrationSource!!.toInt(),evidence.getInt("actual"))
   }
   activity.withVoice{it.wake();wire.emit("open","revision" to wire.revision)}
   await("native output bound"){wire.player.isNotEmpty()}
   val ready=java.util.concurrent.CountDownLatch(1)
   activity.observeNative{if(it.player.observedHead>0)ready.countDown()}
   // head is asynchronous, keep observing without replacing native progress.
   await("native output really progressed"){var head=false;val l=java.util.concurrent.CountDownLatch(1);activity.observeNative{head=it.player.observedHead>0;l.countDown()};l.await(1,java.util.concurrent.TimeUnit.SECONDS);head}
   val audio=ctx.getSystemService(android.media.AudioManager::class.java)
   val config=JSONObject().put("microphone_mute",audio.isMicrophoneMute).put("configs",org.json.JSONArray(audio.activeRecordingConfigurations.map{r->JSONObject().put("session",r.clientAudioSessionId).put("source",r.clientAudioSource).put("client_rate",r.clientFormat.sampleRate).put("client_channels",r.clientFormat.channelCount).put("device_rate",r.format.sampleRate).put("device_channels",r.format.channelCount).put("device",r.audioDevice?.type).put("silenced",if(android.os.Build.VERSION.SDK_INT>=29)r.isClientSilenced else "UNAVAILABLE")}))
   V2HostFixture.evidenceDirectory().resolve("microphone-system-config.json").writeText(config.toString(2))
   gatesAccepted=true
   play("enter")
   timing("COMPLETION_AWAIT_STARTED","enter")
   await("authorized enter fixture playback completed"){completed("enter")}
   timing("COMPLETION_AWAIT_ENDED","enter")
   Thread.sleep(1600);syntheticProbe?.freeze()
   inst.runOnMainSync {activity.pictureResolver={Bitmap.createBitmap(40,40,Bitmap.Config.ARGB_8888).apply{eraseColor(Color.GREEN)}};activity.revealImage("synthetic",1)}
   timing("ENTER_AWAIT_STARTED","enter")
   await("AudioRecord/KWS entered management"){activity.isManaging}
   liveEnter=true
   timing("ENTER_AWAIT_ENDED","enter")
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
   V2HostFixture.evidenceDirectory().resolve("microphone-management.json").writeText(JSONObject().put("real_AudioRecord",true).put("KWS",true).put("network_adapter","synthetic WebSocket; cloud ASR/LLM not tested").put("managed_input_delta",wire.inputs.get()-before).put("timeline",org.json.JSONArray(activity.timelineJson())).toString(2))
  } catch(t:Throwable){primary=t;
   if(requests.containsKey("enter"))try{timing("FIRST_FAILURE","enter")}catch(e:Throwable){t.addSuppressed(e)};try{V2HostFixture.snapshot(activity,"microphone-first")}catch(e:Throwable){t.addSuppressed(e)};throw t
  } finally {
   ownerResume.countDown();activity.afterEligible={}
   var cleanup:Throwable?=null
   try{syntheticProbe?.saveAndReplay()}catch(e:Throwable){cleanup=e}
   var finished=false
   try{V2HostFixture.finish(activity);finished=true}catch(e:Throwable){if(cleanup!=null)cleanup.addSuppressed(e) else cleanup=e}
   if(calibrationSource!=null)try{
    val proof=activity.immediateRecorder()
    V2HostFixture.evidenceDirectory().resolve("arm-${calibrationSource}-${calibrationNonce}-cleanup.json").writeText(JSONObject().put("source",calibrationSource!!.toInt()).put("nonce",calibrationNonce).put("initial_source_configuration",initialSourceEvidence).put("initial_session",initialSession).put("gates_accepted",gatesAccepted && activity.syntheticProbeAllowed() && ctx.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO)==android.content.pm.PackageManager.PERMISSION_GRANTED).put("live_enter",liveEnter).put("finished",finished).put("session",proof.session).put("released",proof.released).put("stopped",proof.stopped).put("recording",proof.recording).put("worker_done",activity.captureWorkerDone).put("lease_available",Capture.leaseAvailable).put("first_failure",primary?.javaClass?.simpleName).toString(2))
   }catch(e:Throwable){if(cleanup!=null)cleanup.addSuppressed(e)else cleanup=e}
   if(cleanup!=null){if(primary!=null)primary.addSuppressed(cleanup)else throw cleanup}
  }
 }
}
