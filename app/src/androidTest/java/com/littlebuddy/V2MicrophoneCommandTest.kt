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
 private fun await(name:String,condition:()->Boolean) {
  val end=SystemClock.elapsedRealtime()+12000
  while(!condition() && SystemClock.elapsedRealtime()<end)Thread.sleep(20)
  assertTrue(name,condition())
 }
 private fun play(name:String) {inst.uiAutomation.executeShellCommand("run-as com.littlebuddy.sim.v2 rm -f files/m06-audio-$name.done").use {java.io.FileInputStream(it.fileDescriptor).readBytes()};inst.sendStatus(30,Bundle().apply{putString("m06_audio",name)})}
 @Test fun actualMicrophoneManagementAndNegativeCommands() {
  val ctx=inst.targetContext
  val activity=inst.startActivitySync(Intent(ctx,V2VoiceActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as V2VoiceActivity
  lateinit var wire:Wire
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
   Thread.sleep(1500)
   inst.runOnMainSync {activity.pictureResolver={Bitmap.createBitmap(40,40,Bitmap.Config.ARGB_8888).apply{eraseColor(Color.GREEN)}};activity.revealImage("synthetic",1)}
   await("AudioRecord/KWS entered management"){activity.isManaging}
   assertFalse(activity.showingImage)
   var released=false;val release=java.util.concurrent.CountDownLatch(1)
   activity.observeNative{released=it.player.binding==null && it.player.stop==StopResult(true,true);release.countDown()};assertTrue(release.await(2,java.util.concurrent.TimeUnit.SECONDS));assertTrue(released)
   val before=wire.inputs.get();wire.emit("reveal","effect" to "synthetic","topic" to 5);wire.emit("audio","player" to wire.player,"stream" to 1,"segment" to "late","start" to 2400,"end" to 2640,"pcm" to android.util.Base64.encodeToString(ByteArray(480),2))
   for(name in listOf("cancel_negative","cancel_discussion","negative_pause_cancel_1.6","cancel_continued_discussion")) {
    play(name);await("audio playback completed: $name"){File(ctx.filesDir,"m06-audio-$name.done").exists()};Thread.sleep(1200)
    assertTrue("negative command must stay managed: $name",activity.isManaging);assertEquals(before,wire.inputs.get());assertFalse(activity.showingImage)
   }
   play("cancel");await("real cancel returns WAKE"){!activity.isManaging && activity.currentMood==EyeMood.WAKE};assertEquals(before,wire.inputs.get())
   play("exit");await("outside exit fixture done"){File(ctx.filesDir,"m06-audio-exit.done").exists()};assertFalse(activity.isManaging)
   play("enter_polite");await("fresh enter through real mic"){activity.isManaging}
   play("exit");await("real exit returns WAKE"){!activity.isManaging && activity.currentMood==EyeMood.WAKE};assertEquals(before,wire.inputs.get())
   val wakes=wire.wakes.get();play("wake");await("next actual wake only"){wire.wakes.get()>wakes}
   File(ctx.filesDir,"m06").mkdirs();File(ctx.filesDir,"m06/microphone-management.json").writeText(JSONObject().put("real_AudioRecord",true).put("KWS",true).put("network_adapter","synthetic WebSocket; cloud ASR/LLM not tested").put("managed_input_delta",wire.inputs.get()-before).put("timeline",org.json.JSONArray(activity.timelineJson())).toString(2))
  } finally {inst.runOnMainSync{activity.finish()}}
 }
}
