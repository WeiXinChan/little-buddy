package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
class NativeLedgerTest {
 private fun rejects(body:()->Unit){try{body();fail("unsafe continuity admitted")}catch(_:IllegalStateException){}}
 @Test fun cumulativeUnreadShrinksRemainingRoomAcrossSubBufferDelays(){
  var now=0L;var frames=0L
  val ledger=NativeReadLedger(3200,{now},{now}){CaptureStamp(frames,now*1_000_000)}
  ledger.check();now=20;frames=320;ledger.read(320)
  now=120;frames=1920;val first=ledger.remainingMs();ledger.read(320)
  now=220;frames=3520
  rejects{ledger.remainingMs()};assertTrue(first<100)
 }
 @Test fun plusAndMinus100ppmFor600SecondsUseHardwarePositionsNotStartClock(){
  for(ppm in listOf(-100L,100L)){
   var now=0L;var position=0L;var stampNs=0L
   val rate=16000L*(1_000_000+ppm)
   val ledger=NativeReadLedger(3200,{now},{now+1000}){CaptureStamp(position,stampNs)}
   for(i in 1..30000){position=i*320L;val numerator=position*1_000_000_000;stampNs=(numerator/rate)*1_000_000+(numerator%rate)*1_000_000/rate
    now=(stampNs+999999)/1_000_000
    ledger.read(320)
    val captured=ledger.sampleTime(position)
    assertTrue(captured<=1000+now);// Existing phase/rounding4ms plus explicit initial offset(-1) and 5ms displacement.
    assertTrue(1000+now-captured<=4+1+CaptureClockBridge.LIMIT_MS)
   }
   assertEquals(9_600_000L,ledger.readSamples)
  }
 }
 @Test fun startDelayDoesNotAssumeSamplesWereCapturedDuringStartCall(){
  // The first hardware pair establishes capture time, including a delayed start.
  var now=500L;var frame=0L
  val ledger=NativeReadLedger(3200,{now},{now+1000}){CaptureStamp(frame,now*1_000_000)}
  ledger.check();now=520;frame=320;assertTrue(ledger.read(320)+1+CaptureClockBridge.LIMIT_MS in 1517..1520)
 }
 @Test fun lateFirstHardwareCounterCannotHideAlreadyOverwrittenSamples(){
  val ledger=NativeReadLedger(3200,{500},{1500}){CaptureStamp(8000,500_000_000)}
  rejects{ledger.check()}
 }
 @Test fun missingStaleAndRelabeledTimestampsNeverCreateFreshBudget(){
  var now=0L;var available=false
  val ledger=NativeReadLedger(3200,{now},{now}){if(available)CaptureStamp(0,0) else null}
  assertFalse(ledger.ready);ledger.remainingMs();assertFalse(ledger.ready)
  now=180;rejects{ledger.remainingMs()}
  now=0;var stamp:CaptureStamp?=CaptureStamp(16,1_000_000)
  val cached=NativeReadLedger(3200,{now},{now}){stamp}
  now=1;cached.read(16);stamp=null;now=90;assertTrue(cached.remainingMs()>0)
  now=102;rejects{cached.remainingMs()}
  now=1;stamp=CaptureStamp(16,1_000_000)
  val relabeled=NativeReadLedger(3200,{now},{now}){stamp};relabeled.read(16)
  now=2;stamp=CaptureStamp(16,2_000_000);rejects{relabeled.remainingMs()}
 }
 @Test fun outOfBoundRateClockJumpAndReadBeyondHardwareAreRejected(){
  var now=1L;var stamp=CaptureStamp(16,1_000_000);var boot=1L
  val ledger=NativeReadLedger(3200,{now},{boot}){stamp};ledger.read(16)
  now=21;boot=21;stamp=CaptureStamp(1000,21_000_000);rejects{ledger.remainingMs()}
  now=1;boot=1;stamp=CaptureStamp(16,1_000_000)
  val jump=NativeReadLedger(3200,{now},{boot}){stamp};jump.read(16);boot=100;rejects{jump.check()}
  val corrupt=NativeReadLedger(3200,{1},{1}){CaptureStamp(Long.MAX_VALUE,1_000_000)};rejects{corrupt.check()}
  val overread=NativeReadLedger(3200,{1},{1}){CaptureStamp(16,1_000_000)};rejects{overread.read(320)}
 }

 @Test fun timestampApiDelayAllowsNewStampAndChargesItsProductionToRoom(){
  var now=0L
  val ledger=NativeReadLedger(3200,{now},{now}){
   now+=10;CaptureStamp(now*16,now*1_000_000)
  }
  val room=ledger.remainingMs()
  assertTrue(ledger.ready)
  // Runtime earliest stamp=8ms and the current mono bin ends11ms: 49 additional possible
  // samples spend room. This tightens169ms to166ms; it does not weaken the old safety bound.
  assertEquals((3200L-320-209)*1000/16016,room)
  assertTrue(room<(3200L-320-160)*1000/16016)
 }
 @Test fun timestampApiDelayAgesOldStampInsteadOfRenewingBudget(){
  var now=1L;var cost=0L;var candidate:CaptureStamp?=CaptureStamp(16,1_000_000)
  val ledger=NativeReadLedger(3200,{now},{now}){now+=cost;candidate}
  ledger.read(16);cost=80;candidate=null
  val room=ledger.remainingMs();assertTrue(room in 1..100)
  cost=21;rejects{ledger.remainingMs()}
 }
}
