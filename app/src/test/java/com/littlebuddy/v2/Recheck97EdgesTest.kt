package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
class Recheck97EdgesTest {
 private class Lab {
  var now=0L; var proposals=0
  val g=InputGate(Waits(),{now},{},{},{},{proposals++},{},{})
 }
 @Test fun ordinarySpeechExpiresWithoutAnyServerReply() {
  val l=Lab();l.g.wake();l.g.speech();l.g.quiet();l.now=15000
  try {l.g.checkResponseDeadline();fail("ordinary expression budget must expire")}catch(_:IllegalStateException){}
 }
 @Test fun futureCaptureBoundaryIsRejected() {
  val l=Lab();l.g.wake()
  try {l.g.speech(1000);fail("future input cannot extend deadline")}catch(_:IllegalArgumentException){}
 }
 @Test fun soloProposalMustAlsoExpireWhenNetworkIsSilent() {
  val l=Lab();l.g.wake();l.now=500;l.g.tick(false);assertEquals(1,l.proposals)
  l.now=15500
  try {l.g.checkResponseDeadline();fail("solo processing must not wait forever without server reply")}catch(_:IllegalStateException){}
 }
}
