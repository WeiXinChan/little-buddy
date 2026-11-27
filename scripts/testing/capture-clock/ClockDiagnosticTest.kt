package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
class ClockDiagnosticTest {
 private fun failure(reason:CaptureClockReason,body:()->Unit):CaptureClockFailure {
  val e=runCatching(body).exceptionOrNull()
  assertTrue("expected typed failure",e is CaptureClockFailure)
  return (e as CaptureClockFailure).also{assertEquals(reason,it.reason)}
 }
 @Test fun schedulingDelayAndStaleStampAreDistinctAndDoNotResetCounters() {
  var now=0L;var s=CaptureStamp(0,0)
  val ledger=NativeReadLedger(3200,{now},{now}){s};ledger.check()
  now=40;s=CaptureStamp(640,40_000_000);ledger.read(640)
  now=250;s=CaptureStamp(4000,250_000_000)
  val e=failure(CaptureClockReason.CUMULATIVE_NATIVE_CONTINUITY_EXHAUSTED){ledger.check()}
  assertEquals(640L,e.evidence.reads);assertEquals(4000L,e.evidence.frames)
  assertEquals(210L,e.evidence.checkGapMs);assertEquals(3360L,e.evidence.deltaFrames)
  now=400
  val stale=failure(CaptureClockReason.TIMESTAMP_STALE){ledger.check()}
  assertEquals(150_000_000L,stale.evidence.ageNs);assertEquals(640L,ledger.readSamples)
 }
 @Test fun pairPhaseRegressionRelabelAndBridgeRemainFailclosed() {
  fun run(reason:CaptureClockReason,stamp:CaptureStamp,bootOffset:Long=0) {
   var now=0L;var boot=0L;var s=CaptureStamp(0,0)
   val ledger=NativeReadLedger(3200,{now},{boot}){s};ledger.check()
   now=20;boot=20;s=CaptureStamp(320,20_000_000);ledger.read(320)
   now=40;boot=40+bootOffset;s=stamp
   val e=failure(reason){ledger.check()};assertEquals(320L,e.evidence.reads)
   assertEquals(stamp.frames,e.evidence.frames);assertEquals(bootOffset,e.evidence.bridgeMs)
  }
  run(CaptureClockReason.PHASE_RATE_MODEL_EXHAUSTED,CaptureStamp(640,35_000_000))
  run(CaptureClockReason.TIMESTAMP_REGRESSED,CaptureStamp(319,40_000_000))
  run(CaptureClockReason.TIMESTAMP_RELABELED,CaptureStamp(320,40_000_000))
  run(CaptureClockReason.TIMEBASE_CHANGED,CaptureStamp(640,40_000_000),6)
 }
 @Test fun detailSinkFailureCannotReplaceOriginalFailureOrThrow() {
  val e=CaptureClockFailure(CaptureClockReason.LONG_RATE_OUTSIDE_BOUND,CaptureClockEvidence(frames=640,reads=320))
  CaptureClockDiagnostic.install{throw IllegalStateException("not observable")}
  try{CaptureClockDiagnostic.emit(e);assertEquals(CaptureClockReason.LONG_RATE_OUTSIDE_BOUND,e.reason)}finally{CaptureClockDiagnostic.install(null)}
 }
 @Test fun recorderStateHasOwnFixedCode() {
  failure(CaptureClockReason.RECORDER_NOT_RECORDING){clockCheck(false,CaptureClockReason.RECORDER_NOT_RECORDING)}
 }
}
