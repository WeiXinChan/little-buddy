package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
class PhasePairTest {
 @Test fun constantTrue16kWithBoundedEndpointPhaseMustNotFailRawLongOracle() {
  val c=CaptureClockEnvelope();c.observe(CaptureStamp(0,0))
  c.observe(CaptureStamp(320,19_550_000))
  for(i in 2..25)c.observe(CaptureStamp(i*320L,i*20_000_000L-450_000))
  println("KNOWN_TRUE16K anchor_f=320 anchor_ns=19550000 end_f=8320 end_ns=520450000 df=8000 dn=500900000; endpoint errors -450us/+450us")
  c.observe(CaptureStamp(8320,520_450_000))
 }
 @Test fun realLongEndpointsAndFiniteBudgetsAreObservableOnlyOnce() {
  val seen=mutableListOf<CaptureClockFailure>();CaptureClockDiagnostic.install{seen.add(it)}
  try {
   constantTrue16kWithBoundedEndpointPhaseMustNotFailRawLongOracle()
   val w=seen.single().longWitness!!
   assertEquals(CaptureClockReason.LONG_RAW_REJECT_PHASE_FEASIBLE,seen.single().reason)
   assertEquals(320L,w.fromFrame);assertEquals(8320L,w.toFrame)
   assertEquals(19_550_000L,w.fromNs);assertEquals(520_450_000L,w.toNs)
   assertEquals(17_984_000_000L,w.lowerBudget);assertEquals(18_016_000_000L,w.upperBudget)
  } finally { CaptureClockDiagnostic.install(null) }
 }
 @Test fun endpointPhaseDoesNotRaiseTrueRateLimitsOrRenewHistoryBudget() {
  for(rate in listOf(15984L,16000L,16016L)) {
   val c=CaptureClockEnvelope()
   for(i in 1..3000) {
    val f=i*320L;val ns=f*1_000_000_000/rate+if(i%2==0)500_000 else -500_000
    c.observe(CaptureStamp(f,ns))
   }
  }
  for(rate in listOf(15982L,16018L)) {
   val c=CaptureClockEnvelope();var failed=false
   for(i in 1..3000) {
    if(runCatching{c.observe(CaptureStamp(i*320L,i*320L*1_000_000_000/rate))}.isFailure){failed=true;break}
   }
   assertTrue("persistent out-of-range rate=$rate",failed)
  }
 }
}
