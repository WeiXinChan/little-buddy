package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
import android.media.AudioRecord
import android.content.res.AssetManager
import android.os.Handler
import com.littlebuddy.SherpaWake
import java.util.concurrent.CountDownLatch
class CaptureSafetyTest {
 private fun batch(n:Int)=List(n){ShortArray(320){7}}
 private fun zero(values:List<ShortArray>)=assertTrue(values.all{a->a.all{it==0.toShort()}})
 @Test fun oneDrainPerRingAndCancellationWipesEverything(){val jobs=mutableListOf<Runnable>();var consumed=0
  val q=CaptureUploads({jobs+=it;true},{1000},{true},{_,_,_->consumed++},{fail("unexpected failure")})
  val a=batch(21);val b=batch(29);assertTrue(q.offer(a,true,1000));assertTrue(q.offer(b,true,1000));assertEquals(1,jobs.size)
  q.cancel();zero(a+b);jobs.single().run();assertEquals(0,consumed)
 }
 @Test fun refusedPostAndOverflowWipeIncludingUnpostedRemainder(){var errors=0
  val q=CaptureUploads({false},{1000},{true},{_,_,_->fail("consume")},{errors++})
  val a=batch(50);assertFalse(q.offer(a,true,1000));zero(a);assertEquals(1,errors)
  val held=mutableListOf<Runnable>();val r=CaptureUploads({held+=it;true},{1000},{true},{_,_,_->fail("consume")},{errors++})
  val b=batch(50);val c=batch(1);assertTrue(r.offer(b,true,1000));assertFalse(r.offer(c,true,1000));zero(b+c);held.single().run();assertEquals(2,errors)
 }
 @Test fun expiryFailsRatherThanDroppingOldSamples(){val jobs=mutableListOf<Runnable>();var time=1000L;var errors=0
  val q=CaptureUploads({jobs+=it;true},{time},{true},{_,_,_->fail("stale PCM")},{errors++})
  val a=batch(21);q.offer(a,true,1000);time=2001;jobs.single().run();zero(a);assertEquals(1,errors)
 }
 @Test fun cancellationDuringDrainWipesLaterFrames(){val jobs=mutableListOf<Runnable>();var count=0;lateinit var q:CaptureUploads
  q=CaptureUploads({jobs+=it;true},{1000},{true},{_,_,_->count++;q.cancel()},{fail("unexpected")})
  q.nativeRoom(6400) // Same configured age bound as the real Capture, no production threshold change.
  val a=batch(50);q.offer(a,true,1000);jobs.single().run();zero(a);assertEquals(1,count)
 }
 @Test fun nativeAndWorkerAndStopAllMustFinishBeforeAnotherOwner(){val a=checkNotNull(ProcessRecorders.acquire("test"))
  try{a.beginStop();a.modelsReleased();a.nativeReleased();assertNull(ProcessRecorders.acquire("new"));a.workerFinished();assertNull(ProcessRecorders.acquire("new"));a.endStop()
   val b=checkNotNull(ProcessRecorders.acquire("management"));b.nativeReleased();b.modelsReleased();b.workerFinished()
  }finally{a.nativeReleased();a.modelsReleased();a.workerFinished()}
 }
 @Test fun workerExitWithoutNativeConfirmationRemainsFailClosed(){val a=checkNotNull(ProcessRecorders.acquire("uncertain"))
  try{a.modelsReleased();a.workerFinished();assertNull(ProcessRecorders.acquire("child"));assertTrue(ProcessRecorders.diagnostic().contains("native_released=false"))}finally{a.nativeReleased()}
 }
 @Test fun callerCancellationStopsNativeWhileOwnerAndModelAreBlocked(){AudioRecord.reset(1);SherpaWake.detectAfter=100
  val block=CountDownLatch(1);SherpaWake.blockClose=block;val owner=Handler();val c=Capture(AssetManager(),owner,VoiceClient(),{true}){}
  c.start();try{
   val end=System.nanoTime()+2_000_000_000;while(AudioRecord.active.get()==0&&System.nanoTime()<end)Thread.sleep(5)
   assertEquals(1,AudioRecord.active.get());c.requestCancel()
   while(AudioRecord.active.get()!=0&&System.nanoTime()<end)Thread.sleep(5)
   assertEquals(0,AudioRecord.active.get());assertTrue(ProcessRecorders.diagnostic().contains("worker_finished=false"));assertNull(ProcessRecorders.acquire("newActivity"))
  }finally{SherpaWake.blockClose=null;block.countDown();c.close();owner.drain()}
 }
 @Test fun originUsesExactFirstFedSampleAcrossPartialReads(){assertEquals(1000L,wakeOrigin(1320,320));assertEquals(1320L,wakeOrigin(1321,1))}
 @Test fun eyesRequireActualNativeEvidenceAndCurrentPageSource(){val state=EyeState();val a=EyeToken(1,1);val b=EyeToken(1,2)
  state.activate(a);state.status(a,"compatibility");assertEquals(EyeMood.CONNECTING,state.mood)
  state.status(a,"wake");assertEquals(EyeMood.IDLE,state.mood)
  state.status(a,"listening");assertEquals(EyeMood.IDLE,state.mood)
  state.beginRecorder(a,4);state.recording(a,4,true);assertEquals(EyeMood.LISTENING,state.mood)
  state.status(a,"speaking");assertEquals(EyeMood.THINKING,state.mood)
  state.output(a,true);assertEquals(EyeMood.PLAYING,state.mood)
  state.activate(b);state.output(a,true);state.recording(a,4,true);assertEquals(EyeMood.IDLE,state.mood)
  state.beginRecorder(b,5);state.recording(b,4,true);assertEquals(EyeMood.IDLE,state.mood)
  state.recording(b,5,true);state.status(b,"wake");assertEquals(EyeMood.WAITING_WAKE,state.mood)
  state.revoke();state.output(b,true);assertEquals(EyeMood.IDLE,state.mood)
  assertEquals(EyeMood.entries.size,EyeMood.entries.map{it.shape()}.toSet().size)
 }

 @Test fun playingEyesWaitForNativeHeadAndStopOnPauseOrRelease(){
  class Track:TrackPort{var position=0L;var plays=0;override val head get()=position
   override fun write(pcm:ShortArray,offset:Int)=pcm.size-offset
   override fun play(){plays++};override fun pause(){};override fun mute(){};override fun flush(){};override fun stop(){};override fun release(){}}
  val track=Track();val state=EyeState();val token=EyeToken(1,1);state.activate(token)
  state.beginRecorder(token,1);state.recording(token,1,true);state.status(token,"speaking")
  val player=Playback({track},{0L}){};player.observeOutput{state.output(token,it)}
  val binding=Binding(0,"p",1);player.bind(binding);player.enqueue(AudioPacket(binding,"s",0,320,ShortArray(320){1}))
  player.tick();assertEquals(1,track.plays);assertEquals(EyeMood.THINKING,state.mood)
  track.position=160;player.tick();assertEquals(EyeMood.PLAYING,state.mood)
  player.suspendOutput();assertEquals(EyeMood.THINKING,state.mood)
  player.resumeConfirmedNoise();assertEquals(EyeMood.THINKING,state.mood)
  track.position=200;player.tick();assertEquals(EyeMood.PLAYING,state.mood)
  track.position=320;player.tick();assertFalse(player.hasPending);assertEquals(EyeMood.THINKING,state.mood)
  player.stop();assertEquals(EyeMood.THINKING,state.mood)
 }
 @Test fun fullRingWaitIsBoundedAndCancelWakesWaiter(){
  val q=CaptureUploads({true},{1000},{true},{_,_,_->},{})
  val a=batch(50);q.offer(a,true,1000)
  val started=CountDownLatch(1);val done=CountDownLatch(1);var result=true
  val worker=Thread{started.countDown();result=q.awaitRoom(320,500);done.countDown()};worker.start();started.await()
  q.cancel();assertTrue(done.await(1,java.util.concurrent.TimeUnit.SECONDS));worker.join();assertFalse(result);zero(a)
  val r=CaptureUploads({true},{1000},{true},{_,_,_->},{})
  r.offer(batch(50),true,1000);assertFalse(r.awaitRoom(320,5));r.cancel()
 }

 @Test fun consumeExceptionWipesCurrentAndRemainingBatchExactlyOnce(){val jobs=mutableListOf<Runnable>();var errors=0;var delivered=0
  val q=CaptureUploads({jobs+=it;true},{1000},{true},{_,_,_->delivered++;error("synthetic sink failure")},{errors++})
  q.nativeRoom(6400) // Production always configures the actual native buffer before offer.
  val a=batch(50);q.offer(a,true,1000);jobs.single().run();zero(a);assertEquals(1,delivered);assertEquals(1,errors)
 }
 @Test fun cancellationAcrossNativeConstructionAndStartNeverAdmitsAnotherOwner(){
  for(stage in 0..2){AudioRecord.reset(1);SherpaWake.detectAfter=100
   val entered=CountDownLatch(1);val release=CountDownLatch(1)
   val hook:()->Unit={entered.countDown();release.await()}
   when(stage){0->AudioRecord.beforeConstruct=hook;1->AudioRecord.beforeStart=hook;else->AudioRecord.afterStart=hook}
   val h=Handler();val c=Capture(AssetManager(),h,VoiceClient(),{true}){}
   c.start();try{assertTrue(entered.await(2,java.util.concurrent.TimeUnit.SECONDS));c.requestCancel()
    val m=ManagementCapture(AssetManager(),h,{true},{},{})
    m.start();assertTrue(m.quarantined);assertTrue(AudioRecord.made.get()<=1)
   }finally{release.countDown();c.close();h.drain()}
   assertEquals(0,AudioRecord.active.get())
   val end=System.nanoTime()+1_000_000_000
   while(ProcessRecorders.diagnostic()!="released"&&System.nanoTime()<end)Thread.sleep(5)
   assertEquals("released",ProcessRecorders.diagnostic())
  }
 }

 @Test fun managementDecodeCancelStopsNativeWithoutOwnerAndDiscardsResult(){
  val d=com.k2fsa.sherpa.onnx.DecodeScenario;d.reset();d.ready=true;AudioRecord.reset(1)
  val entered=CountDownLatch(1);val release=CountDownLatch(1);d.onDecode={entered.countDown();release.await()}
  val h=Handler();var exits=0;var results=-1;val m=ManagementCapture(AssetManager(),h,{true},{exits++},{})
  m.start();try{assertTrue(entered.await(2,java.util.concurrent.TimeUnit.SECONDS));m.requestCancel()
   val end=System.nanoTime()+1_000_000_000;while(AudioRecord.active.get()!=0&&System.nanoTime()<end)Thread.sleep(5)
   assertEquals(0,AudioRecord.active.get());assertNull(ProcessRecorders.acquire("child"))
  }finally{release.countDown();m.close();h.drain();results=d.results;d.reset()}
  assertEquals(0,exits);assertEquals(0,results)
 }

 @Test fun ownerStallBeyondNativeRoomFailsInsteadOfRelabelingOrDelivering(){
  AudioRecord.reset(50);SherpaWake.detectAfter=50;val h=Handler();val client=VoiceClient();var failures=0
  val c=Capture(AssetManager(),h,client,{true}){failures++};c.start()
  try{val end=System.nanoTime()+2_000_000_000
   while(!c.nativeProof.released&&System.nanoTime()<end)Thread.sleep(5)
   assertTrue(c.nativeProof.released);h.drain();assertEquals(0,client.received.size);assertTrue(failures>0)
  }finally{c.close();h.drain()}
 }

 @Test fun acceptedEndpointWaitIsChildWaitUntilActualSealAndFaultNeverLooksAwake(){
  val state=EyeState();val token=EyeToken(1,1);state.activate(token);state.beginRecorder(token,1);state.recording(token,1,true)
  var time=1000L
  val gate=InputGate(Waits(),{time},{},{},{state.status(token,"thinking")},{},{},{})
  gate.wake();gate.speech();gate.quiet()
  for(completion in Completion.entries){assertTrue(gate.decision(gate.revision,completion));state.status(token,completion.eyeStatus());assertEquals(EyeMood.WAITING_CHILD,state.mood)}
  assertFalse(gate.decision(gate.revision-1,Completion.COMPLETE));assertEquals(EyeMood.WAITING_CHILD,state.mood)
  gate.decision(gate.revision,Completion.COMPLETE);state.status(token,Completion.COMPLETE.eyeStatus());time+=1000;gate.tick(false)
  assertEquals(EyeMood.THINKING,state.mood)
  for(code in listOf("failure","route","unknown")){state.status(token,code);state.recording(token,1,false);assertEquals(EyeMood.FAULT,state.mood)}
  state.status(token,"clarify");state.recording(token,1,true);assertEquals(EyeMood.WAITING_CHILD,state.mood)
 }
 @Test fun modelUncertaintyAndBatchDurationReachFirstSampleAgeAtActualConsumer(){
  var now=1000L;var stamp=CaptureStamp(0,1_000_000_000)
  val ledger=NativeReadLedger(3200,{now},{now}){stamp}
  ledger.check();now=1040;stamp=CaptureStamp(640,1_040_000_000);val end=ledger.read(640)
  assertEquals(1037L,end)
  val jobs=mutableListOf<Runnable>();val seen=mutableListOf<Long>()
  val q=CaptureUploads({jobs+=it;true},{now},{true},{_,_,at->seen+=at},{fail("unexpected")})
  q.offer(batch(2),true,end);jobs.single().run()
  assertEquals(listOf(996L,1016L),seen)
  assertTrue(seen[0]<=ledger.sampleTime(0));assertTrue(seen[1]<=ledger.sampleTime(320))
  var delivered=0;var failures=0;jobs.clear()
  val expired=CaptureUploads({jobs+=it;true},{now},{true},{_,_,_->delivered++},{failures++})
  val data=batch(2);expired.offer(data,true,end);now=1998;jobs.single().run()
  assertEquals(0,delivered);assertEquals(1,failures);zero(data)
 }

}
