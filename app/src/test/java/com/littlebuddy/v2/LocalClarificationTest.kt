package com.littlebuddy.v2

import org.junit.Assert.*
import org.junit.Test

class LocalClarificationTest {
 private class Native:TrackPort {
  override var head=0L;var written=0L;val cleanup=mutableListOf<String>();var volume=0
  override fun write(pcm:ShortArray,offset:Int):Int {val n=minOf(240,pcm.size-offset);written+=n;return n}
  override fun setVolume(percent:Int):Boolean {volume=percent;return true}
  override fun play(){}
  override fun pause(){cleanup+="pause"};override fun mute(){cleanup+="mute"}
  override fun flush(){cleanup+="flush"};override fun stop(){cleanup+="stop"};override fun release(){cleanup+="release"}
 }
 @Test fun localDoesNotBindAckOrOverlapNormalAndCompletesAfterHeadAndRelease(){
  val n=Native();var acks=0;var heads=0;var ends=0
  val p=Playback({n},{100L}){acks++};val pcm=ShortArray(480){9}
  p.clarify(1,pcm,{heads++},{assertTrue(n.cleanup.contains("release"));ends++},{fail("unexpected cancellation")})
  assertNull(p.binding)
  try{p.bind(Binding(1,"normal",1));fail()}catch(_:IllegalStateException){}
  p.tick();assertEquals(0,heads);n.head=240;p.tick();n.head=480;p.tick()
  assertEquals(1,heads);assertEquals(1,ends);assertEquals(0,acks)
  assertTrue(pcm.all{it==0.toShort()});assertFalse(p.localActive)
 }
 @Test fun throwingCancelAndOutputObserverCannotPreventCleanupOrRebindOldNative(){
  val n=Native();val p=Playback({n},{100L}){}
  p.observeOutput{if(!it)throw AssertionError("observer")}
  p.clarify(1,ShortArray(480),{}, {}, {
   assertEquals(listOf("mute","pause","flush","stop","release"),n.cleanup)
   try{p.bind(Binding(2,"reentrant",2));fail()}catch(_:IllegalStateException){}
   throw AssertionError("cancel observer")
  })
  p.tick();n.head=240;p.tick()
  assertEquals(StopResult(true,true),p.stop());assertEquals(StopResult(true,true),p.stop())
  assertNull(p.binding);assertEquals(5,n.cleanup.size)
 }
 @Test fun throwingHeadStillReleasesAndClearsPrefix(){
  val n=Native();val p=Playback({n},{100L}){};val pcm=ShortArray(480){9}
  p.clarify(1,pcm,{throw AssertionError("head observer")},{},{})
  p.tick();n.head=240
  try{p.tick();fail()}catch(_:AssertionError){}
  assertTrue(n.cleanup.contains("release"));assertFalse(p.localActive);assertTrue(pcm.all{it==0.toShort()})
 }
 @Test fun throwingFinishedIsAfterReleaseAndCannotResurrectOldPurpose(){
  val n=Native();val p=Playback({n},{100L}){}
  p.clarify(1,ShortArray(240),{}, {assertTrue(n.cleanup.contains("release"));throw AssertionError("finish observer")},{})
  p.tick();n.head=240
  try{p.tick();fail()}catch(_:AssertionError){}
  assertEquals(1,n.cleanup.count{it=="release"});assertFalse(p.localActive)
 }
 @Test fun cancellationFromHeadWinsBeforeAnyFurtherWrite(){
  val n=Native();val p=Playback({n},{100L}){};var ends=0
  p.clarify(1,ShortArray(480),{p.stop()},{ends++},{})
  p.tick();n.head=240;p.tick()
  assertEquals(240L,n.written);assertEquals(0,ends);assertTrue(n.cleanup.contains("release"))
 }
 @Test fun refusedLocalAcquisitionCannotStopNormalBinding(){
  val n=Native();val p=Playback({n},{100L}){};val binding=Binding(1,"normal",1);p.bind(binding)
  val pcm=ShortArray(480){9}
  try{p.clarify(1,pcm,{}, {}, {});fail()}catch(_:IllegalStateException){}
  assertEquals(binding,p.binding);assertTrue(n.cleanup.isEmpty());assertTrue(pcm.all{it==0.toShort()})
  p.stop()
 }
 @Test fun localResourceDeadlineFailsClosedWithoutWaitingForAudio(){
  val n=Native();var time=100L;val p=Playback({n},{time}){}
  p.clarify(1,ShortArray(480),{}, {}, {});time=10100
  try{p.tick();fail()}catch(_:IllegalStateException){}
  assertEquals(0L,n.written);assertTrue(n.cleanup.contains("release"))
 }
}
