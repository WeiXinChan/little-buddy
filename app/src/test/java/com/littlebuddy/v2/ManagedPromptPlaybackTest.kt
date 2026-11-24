package com.littlebuddy.v2
import org.junit.Test
import org.junit.Assert.*
class ManagedPromptPlaybackTest {
 private class Native:TrackPort {
  var position=0L;var released=false
  override val head get()=position
  override fun write(pcm:ShortArray,offset:Int)=pcm.size-offset
  override fun play(){};override fun pause(){};override fun mute(){};override fun flush(){};override fun stop(){};override fun release(){released=true}
 }
 @Test fun completionRequiresRealPortHeadThenStopAndRelease(){val n=Native();val p=ManagedPromptPlayback({n},{0L},{true});p.begin(ShortArray(4800){1});p.tick();assertNull(p.result);n.position=2400;p.tick();assertNull(p.result);n.position=4800;p.tick();assertEquals(true,p.result);assertTrue(n.released);assertEquals(StopResult(true,true),p.proof.stop)}
 @Test fun silentOrUnknownRouteNeverSucceeds(){val p=ManagedPromptPlayback({Native()},{0L},{false});p.begin(ShortArray(2400){1});assertEquals(false,p.result)}
 @Test fun timeoutAndCancelCannotAcknowledgePlayback(){var t=0L;val n=Native();val p=ManagedPromptPlayback({n},{t},{true});p.begin(ShortArray(2400){1});p.tick();t=6001;p.tick();assertEquals(false,p.result);assertTrue(n.released);p.cancel();assertEquals(false,p.result)}
 @Test fun routeLossEvenWithProgressFailsClosed(){var routed=true;val n=Native();val p=ManagedPromptPlayback({n},{0L},{routed});p.begin(ShortArray(2400){1});p.tick();n.position=2400;routed=false;p.tick();assertEquals(false,p.result);assertTrue(n.released)}
}
