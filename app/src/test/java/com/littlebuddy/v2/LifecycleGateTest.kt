package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
class LifecycleGateTest {
 @Test fun queuedStartsAndAfterEligibilityRaceAreCancelled() {
  val gate=LifecycleGate();gate.resume();val first=gate.focus(true)
  val passed=CountDownLatch(1);val consume=CountDownLatch(1);var starts=0
  val owner=Thread { assertTrue(gate.allows(first));passed.countDown();consume.await();if(gate.allows(first))starts++ }
  owner.start();assertTrue(passed.await(1,TimeUnit.SECONDS))
  gate.focus(false);gate.focus(true);gate.focus(false);gate.pause()
  consume.countDown();owner.join(1000)
  assertEquals(0,starts);assertFalse(gate.allows(first))
 }
 @Test fun resumedGenerationCannotReviveOldCloudOrLocalStart() {
  val gate=LifecycleGate();gate.resume();val old=gate.focus(true)
  gate.pause();gate.focus(false);gate.resume();val next=gate.focus(true)
  assertFalse(gate.allows(old));assertTrue(gate.allows(next))
  gate.destroy();assertFalse(gate.allows(next))
 }
 @Test fun timelineIsBoundedAndMonotonic() {
  var now=0L;val t=StopTimeline { now++ }
  repeat(300){t.add("STOP_ENQUEUE")}
  assertEquals(256,t.snapshot().size);assertTrue(t.snapshot().zipWithNext().all{it.first.ms<=it.second.ms})
 }
}
