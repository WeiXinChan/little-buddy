package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
class ReadFrontierTest {
 @Test fun refinedClockMustNotAdmitAlreadyReadSamplesBeyondProducedUpper(){
  var now=1000L;var stamp:CaptureStamp?=null
  val ledger=NativeReadLedger(3200,{now},{now}){stamp}
  ledger.beginStartup();now=1041;stamp=CaptureStamp(640,1040000000)
  ledger.stageRead(320);ledger.stageRead(320);ledger.stageRead(32)
  assertEquals(672L,ledger.readSamples)
  stamp=CaptureStamp(641,1041000000)
  val failure=runCatching{ledger.finishStartup()}.exceptionOrNull()
  val later=runCatching{ledger.read(0)}.exceptionOrNull()
  println("frontier admission_error=${failure?.message}, next_read_error=${later?.message}, read=${ledger.readSamples}")
  assertNotNull("admission must reject a model whose produced upper666 is below known native read672",failure)
 }
}
