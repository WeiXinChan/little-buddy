package com.littlebuddy
import org.junit.Assert.*
import org.junit.Test
import android.content.res.AssetManager
import com.k2fsa.sherpa.onnx.DecodeScenario as D
class WakeCancellationTest {
 @Test fun optionalDefaultPreservesWakeTimestampAndKeyword(){D.reset();D.ready=true
  SherpaWake(AssetManager()).use {assertEquals(1920L,it.accept(ShortArray(320){7},320));assertEquals(1,D.decodes);assertEquals(1,D.results)}
 }
 @Test fun cancellationAfterWaveformDoesNotEnterDecodeAndWipesFloatCopy(){D.reset();D.ready=true;var allowed=true;D.onAccept={allowed=false}
  SherpaWake(AssetManager()){allowed}.use{assertNull(it.accept(ShortArray(320){7},320))}
  assertEquals(0,D.decodes);assertTrue(D.floats!!.all{it==0f})
 }
 @Test fun cancellationAfterIsReadyDoesNotDecode(){D.reset();D.ready=true;var allowed=true;D.onReady={allowed=false}
  SherpaWake(AssetManager()){allowed}.use{assertNull(it.accept(ShortArray(320),320))};assertEquals(0,D.decodes)
 }
 @Test fun cancellationDuringDecodeRejectsLateResult(){D.reset();D.ready=true;var allowed=true;D.onDecode={allowed=false}
  SherpaWake(AssetManager()){allowed}.use{assertNull(it.accept(ShortArray(320),320))};assertEquals(1,D.decodes);assertEquals(0,D.results)
 }
 @Test fun cancellationAfterResultDoesNotWake(){D.reset();D.ready=true;var allowed=true;D.onResult={allowed=false}
  SherpaWake(AssetManager()){allowed}.use{assertNull(it.accept(ShortArray(320),320))};assertEquals(1,D.results)
 }
}
