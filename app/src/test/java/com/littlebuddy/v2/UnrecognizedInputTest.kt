package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
class UnrecognizedInputTest {
 private class Rig {
  var now=0L;var probes=0;var seals=0;var solos=0
  val g=InputGate(Waits(),{now},{},{probes++},{seals++},{solos++},{},{})
  fun speech(){g.wake();g.speech(now);g.quiet();now+=301;g.tick(false)}
 }
 @Test fun terminalClearsWholeWaitAndNaturalNextSpeechHasOriginalBudget(){
  val r=Rig();r.speech();val deadline=r.g.responseDeadline;val capture=r.g.capturedLastSpeechBootMs
  assertTrue(r.g.unrecognized(1));assertFalse(r.g.unrecognized(1));r.now=16000;r.g.tick(false)
  assertTrue(r.g.awake);assertEquals(deadline,r.g.responseDeadline);assertEquals(capture,r.g.capturedLastSpeechBootMs)
  assertEquals(1,r.probes);assertEquals(0,r.seals);assertEquals(0,r.solos)
  r.g.speech(16000);r.g.quiet();r.now=16301;r.g.tick(false)
  assertEquals(2L,r.g.revision);assertEquals(31000L,r.g.responseDeadline);assertEquals(2,r.probes)
 }
 @Test fun sealedUnknownCanTerminateWithoutPretendingEffectivePlayback(){
  val r=Rig();r.speech();r.g.decision(1,Completion.COMPLETE);r.now=1000;r.g.tick(false);assertEquals(1,r.seals)
  assertTrue(r.g.unrecognized(1));assertEquals(15000L,r.g.responseDeadline);r.now=16000;r.g.checkResponseDeadline()
 }
 @Test fun expiredCannotBeClearedAndStillFailsTheOriginalDeadline(){
  val r=Rig();r.speech();r.now=15000
  try{r.g.unrecognized(1);fail()}catch(_:IllegalStateException){}
  try{r.g.checkResponseDeadline();fail()}catch(_:IllegalStateException){}
  assertEquals(15000L,r.g.responseDeadline)
 }
 @Test fun staleVersionSpeakingAndNoCapturedInputCannotTerminate(){
  val r=Rig();r.g.wake();r.now=600;r.g.tick(false);assertFalse(r.g.unrecognized(0))
  r.g.speech(600);assertFalse(r.g.unrecognized(1));r.g.quiet();assertFalse(r.g.unrecognized(0))
  r.now=15600;try{r.g.checkResponseDeadline();fail()}catch(_:IllegalStateException){}
 }
 @Test fun incompleteThinkingKeepTheirOriginalWaitUnlessExplicitTerminalArrives(){
  for(c in listOf(Completion.INCOMPLETE,Completion.THINKING)){
   val r=Rig();r.speech();r.g.decision(1,c);r.now=1500;r.g.tick(false)
   assertEquals(0,r.seals);assertEquals(c,r.g.endpointCompletion)
   assertTrue(r.g.unrecognized(1));assertNull(r.g.endpointCompletion);assertEquals(15000L,r.g.responseDeadline)
  }
 }
 @Test fun effectiveResponseNoiseAndManagementDenyLateTerminal(){
  val r=Rig();r.speech();r.g.effectivePlayed();assertFalse(r.g.unrecognized(1))
  r.g.speech(r.now);r.g.quiet();r.g.noResponseExpected();assertFalse(r.g.unrecognized(2))
  r.g.managementWaiting(2);assertFalse(r.g.unrecognized(2))
 }
}
