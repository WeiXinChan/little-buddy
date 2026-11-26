package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
class DevicePhaseTest {
 @Test fun observedAdjacentDeltaNeedsFiniteLargerRuntimePhase() {
  val c=CaptureClockEnvelope()
  c.observe(CaptureStamp(71360,4_460_000_000))
  // Exact device df/dn, common origin removed; not reconstruction of all device history.
  c.observe(CaptureStamp(71680,4_481_087_384))
 }
 @Test fun actualRawLongEndpointsAdmitWithinBoundedModel() {
  val c=CaptureClockEnvelope()
  c.observe(CaptureStamp(11520,86552077794158))
  c.observe(CaptureStamp(20160,86552618798774))
 }
 @Test fun boundedRuntimeJitterForNinetySecondsHasNoGrowingPhaseAllowance() {
  val c=CaptureClockEnvelope()
  for(i in 1..4500)c.observe(CaptureStamp(i*320L,i*20_000_000L+if(i%2==0)1_500_000 else -1_500_000))
  val jump=CaptureClockEnvelope();jump.observe(CaptureStamp(320,20_000_000))
  assertNotNull(runCatching{jump.observe(CaptureStamp(640,45_000_000))}.exceptionOrNull())
 }
 @Test fun startupKeepsTightOriginThenRuntimeSpendsMoreRoomWithoutResettingReads() {
  var now=0L;var stamp=CaptureStamp(0,0)
  val ledger=NativeReadLedger(3200,{now},{now}){stamp};ledger.beginStartup()
  now=20;stamp=CaptureStamp(320,20_000_000);ledger.stageRead(320)
  now=40;stamp=CaptureStamp(640,40_000_000);ledger.stageRead(320)
  val oldRoom=ledger.remainingMs();val oldZero=ledger.sampleTime(0)
  ledger.finishStartup()
  assertEquals(640L,ledger.readSamples)
  assertTrue(ledger.remainingMs()<oldRoom)
  assertTrue(ledger.sampleTime(0)<oldZero)
  assertEquals(-4L,ledger.sampleTime(0))
  now=61;stamp=CaptureStamp(960,61_087_384);ledger.read(320)
  assertEquals(960L,ledger.readSamples)
 }
}
