package com.littlebuddy
import android.media.AudioManager
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import com.littlebuddy.v2.*
import org.junit.Test
import org.junit.Assert.*
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
class V2LocalPromptTest {
 private fun runPrompt(mute:Boolean,cancel:Boolean){
  val i=InstrumentationRegistry.getInstrumentation();val manager=i.targetContext.getSystemService(AudioManager::class.java)
  val old=manager.getStreamVolume(AudioManager.STREAM_MUSIC);val muted=manager.isStreamMute(AudioManager.STREAM_MUSIC)
  val thread=HandlerThread("local-prompt-proof").apply{start()};val owner=Handler(thread.looper);val done=CountDownLatch(1)
  val result=AtomicReference<Boolean>();val proof=AtomicReference<PlayerProof>();val failure=AtomicReference<Throwable>()
  i.uiAutomation.adoptShellPermissionIdentity("android.permission.MODIFY_AUDIO_SETTINGS")
  try {
   manager.setStreamVolume(AudioManager.STREAM_MUSIC,if(mute)0 else maxOf(1,old),0)
   assertEquals("actual AVD media mute fixture",mute,manager.getStreamVolume(AudioManager.STREAM_MUSIC)==0)
   val bytes=i.targetContext.assets.open("management/confirm_prompt.wav").use{it.readBytes()};val pcm=ShortArray((bytes.size-44)/2);ByteBuffer.wrap(bytes,44,bytes.size-44).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(pcm)
   owner.post {
    var native:AndroidTrack?=null
    val cue=ManagedPromptPlayback({AndroidTrack(owner){}.also{native=it}},SystemClock::elapsedRealtime,{manager.getStreamVolume(AudioManager.STREAM_MUSIC)>0 && !manager.isStreamMute(AudioManager.STREAM_MUSIC) && (native?.head==0L || native?.hasRoute==true || native==null)})
    try{cue.begin(pcm)}catch(t:Throwable){failure.set(t);done.countDown();return@post}
    fun pump(){try{cue.tick();if(cancel && cue.proof.observedHead>0)cue.cancel();if(cue.result==null)owner.postDelayed({pump()},10) else {result.set(cue.result);proof.set(cue.proof);done.countDown()}}catch(t:Throwable){cue.cancel();failure.set(t);done.countDown()}}
    pump()
   }
   assertTrue("bounded actual native prompt execution",done.await(9,TimeUnit.SECONDS));failure.get()?.let{throw it}
   assertEquals("only full real playback can acknowledge",!mute && !cancel,result.get())
   if(!mute){assertTrue("real AudioTrack head advances",proof.get().observedHead>0);assertEquals(StopResult(true,true),proof.get().stop)}
   val dir=V2HostFixture.evidenceDirectory();java.io.File(dir,"local-prompt-$mute-$cancel.txt").writeText("result=${result.get()} proof=${proof.get()} emulator=true")
  }finally{
   manager.setStreamVolume(AudioManager.STREAM_MUSIC,old,0);manager.adjustStreamVolume(AudioManager.STREAM_MUSIC,if(muted)AudioManager.ADJUST_MUTE else AudioManager.ADJUST_UNMUTE,0)
   i.uiAutomation.dropShellPermissionIdentity();thread.quitSafely();thread.join(2000)
  }
 }
 @Test fun completeRealNativePrompt()=runPrompt(false,false)
 @Test fun mutedActualMediaRouteCannotAcknowledge()=runPrompt(true,false)
 @Test fun cancelledNativePromptStopsAndReleasesWithoutAck()=runPrompt(false,true)
}
