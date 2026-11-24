package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
class CaptureReadSnapshotTest {
 @Test fun oldReadingRecorderCannotSatisfyQueuedNewIntent(){
  val old=CaptureReadSnapshot(7,7,null,11,11,16000,true)
  assertTrue(old.reading)
  assertFalse(old.readyFor("new",CaptureInput.COMMUNICATION))
  assertFalse(old.readyFor("new",CaptureInput.RECOGNITION))
  val next=CaptureReadSnapshot(6,6,"new",12,12,320,true)
  assertTrue(next.readyFor("new",CaptureInput.RECOGNITION))
  assertFalse(next.copy(nativeSession=11).readyFor("new",CaptureInput.RECOGNITION))
  assertFalse(next.copy(nonce="old").readyFor("new",CaptureInput.RECOGNITION))
  assertFalse(next.copy(frames=0).readyFor("new",CaptureInput.RECOGNITION))
 }
}
