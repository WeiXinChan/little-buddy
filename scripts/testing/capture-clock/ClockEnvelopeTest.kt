package com.littlebuddy.v2

import java.io.File
import org.junit.Assert.*
import org.junit.Test

class ClockEnvelopeTest {
 private fun rejects(body:()->Unit):Throwable {
  val error=runCatching(body).exceptionOrNull();assertNotNull("unsafe model admitted",error);return checkNotNull(error)
 }
 @Test fun actual151RowTraceReplaysThroughProductionLedgerWithoutRebasingReadOrigin(){
  val rows=File(System.getProperty("capture.trace")).readLines().map{it.split('\t').map(String::toLong)}
  assertEquals(151,rows.size)
  val origin=(rows[0][3]-153252308)/1_000_000
  var now=origin;var boot=origin;var current:List<Long>?=null
  val ledger=NativeReadLedger(3200,{now},{boot}){
   current?.let{now=it[3]/1_000_000;boot=it[4]/1_000_000;CaptureStamp(it[0],it[1])}
  }
  ledger.beginStartup();var anchored=false;var minimumRoom=Long.MAX_VALUE;var admittedAt=-1L
  for((i,row) in rows.withIndex()) {
   current=row;now=row[2]/1_000_000;boot=now
   val increment=(row[5]-ledger.readSamples).toInt();assertTrue(increment>=0)
   if(!anchored){ledger.stageRead(increment)
    if(ledger.startupAnchored){ledger.finishStartup();anchored=true;admittedAt=now-origin}
   }else ledger.read(increment)
   minimumRoom=minOf(minimumRoom,ledger.remainingMs())
   assertEquals("row$i",row[5],ledger.readSamples)
   assertTrue(ledger.sampleTime(0)>=origin-2)
  }
  assertTrue(anchored);assertTrue(admittedAt in 1..499);assertTrue(minimumRoom>0)
  println("RAW_TRACE rows=${rows.size} anchored_ms=$admittedAt reads=${ledger.readSamples} min_room_ms=$minimumRoom; metadata replay NOT device production PASS")
 }
 @Test fun boundedPhaseJitterIsNotConstantDriftAndLongRateStaysUnchanged(){
  val clock=CaptureClockEnvelope()
  for(i in 0..1000)clock.observe(CaptureStamp(i*320L,i*20_000_000L+if(i%2==0)200_000 else -200_000))
  for(rate in listOf(15952L,16048L)) {
   val c=CaptureClockEnvelope();var failure:Throwable?=null;var seen=0
   for(i in 0..200){seen=i;failure=runCatching{c.observe(CaptureStamp(i*320L,i*320L*1_000_000_000/rate))}.exceptionOrNull();if(failure!=null)break}
   assertNotNull("sustained rate=$rate",failure);assertTrue(seen<100)
  }
 }
 @Test fun suddenPhaseJumpAndAccumulatingOutOfBoundWalkAreRejected(){
  val jump=CaptureClockEnvelope();jump.observe(CaptureStamp(0,0));jump.observe(CaptureStamp(320,20_000_000))
  rejects{jump.observe(CaptureStamp(640,45_000_000))}
  val walk=CaptureClockEnvelope();var failed=false
  for(i in 0..100){if(runCatching{walk.observe(CaptureStamp(i*320L,i*20_000_000L+i*40_000L))}.isFailure){failed=true;break}}
  assertTrue(failed)
 }
 @Test fun everyEligibleLongPairIsCheckedNotOnlyFirstOrLatest(){
  // All points remain in the +/-0.5ms phase model, but this 500ms raw pair violates the
  // original +/-1000ppm,+/-2-frame oracle. A first-only or reset window would miss it.
  val c=CaptureClockEnvelope()
  c.observe(CaptureStamp(0,0));c.observe(CaptureStamp(320,20_000_000-450_000))
  for(i in 2..25)c.observe(CaptureStamp(i*320L,i*20_000_000L-450_000))
  val e=rejects{c.observe(CaptureStamp(26*320L,26*20_000_000L+450_000))}
  assertEquals("capture long rate outside bound",e.message)
 }
 @Test fun uncertaintySpendsNativeRoomAndMakesSampleTimeEarlier(){
  var now=0L;var stamp=CaptureStamp(0,0)
  val ledger=NativeReadLedger(3200,{now},{now}){stamp}
  ledger.check();now=110;stamp=CaptureStamp(1600,100_000_000)
  val room=ledger.remainingMs()
  // Earliest true stamp >=99.5ms; floor mono bin ends111ms => upper1785 frames, room68ms.
  assertEquals((2880L-1785)*1000/16016,room)
  assertTrue(ledger.sampleTime(0)<=-2)
  now=200;assertNotNull(runCatching{ledger.check()}.exceptionOrNull())
 }
 @Test fun modelBoundsAreFiniteAndRegressionsCannotResetThem(){
  val c=CaptureClockEnvelope();c.observe(CaptureStamp(320,20_000_000))
  rejects{c.observe(CaptureStamp(319,40_000_000))}
  val d=CaptureClockEnvelope();d.observe(CaptureStamp(320,20_000_000))
  rejects{d.observe(CaptureStamp(640,19_000_000))}
 }
 @Test fun earliestTimestampAgeAndMissingApiStillExpireWithoutRenewal(){
  var now=1L;var available=true
  val ledger=NativeReadLedger(3200,{now},{now}){if(available)CaptureStamp(16,1_000_000) else null}
  ledger.read(16);available=false;now=99;assertTrue(ledger.remainingMs()>0)
  now=100;assertEquals("capture timestamp stale",rejects{ledger.check()}.message)
 }

 @Test fun nearBoundaryDriftCannotRenewItsErrorBudgetEveryHalfSecond(){
  fun time(frames:Long,ppm:Long):Long {
   val n=frames*1_000_000_000;val rate=16000L*(1_000_000+ppm)
   return (n/rate)*1_000_000+(n%rate)*1_000_000/rate
  }
  for(ppm in listOf(-1250L,-1100L,1100L,1250L)) {
   val c=CaptureClockEnvelope();var rejectedAt=-1
   for(i in 0..3000){if(runCatching{c.observe(CaptureStamp(i*320L,time(i*320L,ppm)))}.isFailure){rejectedAt=i;break}}
   assertTrue("persistent drift $ppm never rejected",rejectedAt>0 && rejectedAt<3000)
   println("NEAR_BOUNDARY ppm=$ppm reject_frame=${rejectedAt*320} reject_nominal_ms=${rejectedAt*20}")
  }
  for(ppm in listOf(-1000L,1000L)) {
   val c=CaptureClockEnvelope()
   for(i in 0..3000)c.observe(CaptureStamp(i*320L,time(i*320L,ppm)))
  }
 }

}
