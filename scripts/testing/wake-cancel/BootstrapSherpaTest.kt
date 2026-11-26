package com.littlebuddy
import com.littlebuddy.v2.*
import com.k2fsa.sherpa.onnx.DecodeScenario
import android.content.res.AssetManager
import org.junit.Assert.*
import org.junit.Test

/** Real SherpaWake implementation, controlled ONNX/native ports; no acoustic accuracy claim. */
class BootstrapSherpaTest {
 @Test fun delayedAnchorFeedsRealSherpaFromSampleZeroOnlyAfterAdmission(){
  var now=1000L;var read=0;var accepts=0
  val origin=now
  DecodeScenario.reset();DecodeScenario.onAccept={accepts++}
  val ledger=NativeReadLedger(3200,{now},{now}){
   if(now-origin<250)null else CaptureStamp((now-origin)*16,now*1_000_000)
  }
  val prefix=CaptureBootstrap(ledger)
  val wake=SherpaWake(AssetManager())
  try {
   prefix.prepare({frame->assertEquals(0,accepts);now+=20
    repeat(320){frame[it]=(read+it+1).toShort()};read+=320;320},{true},{now+=5})
   assertEquals(0,accepts);assertEquals(read.toLong(),ledger.readSamples)
   val frame=ShortArray(320);var position=0
   while(prefix.pending){val n=prefix.take(frame)
    assertEquals((position+1).toShort(),frame[0]);wake.accept(frame,n);position+=n
    assertTrue(DecodeScenario.floats!!.all{it==0f});frame.fill(0)
   }
   assertEquals(read,position);assertTrue(accepts>0)
   assertTrue(ledger.sampleTime(0) in origin-2..origin)
   assertTrue(ledger.sampleTime(1920) in origin+118..origin+120)
  }finally{prefix.clear();wake.close();DecodeScenario.reset()}
 }
}
