package com.littlebuddy
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Test
import org.junit.Assert.*
import java.nio.ByteBuffer
import java.nio.ByteOrder
class V2ModelResetTest {
 @Test fun sameNativeWakeModelFreshStreamsKeepAbsoluteTailAndDiscardOldHits(){
  val i=InstrumentationRegistry.getInstrumentation();val bytes=i.context.assets.open("m06-commands/wake.wav").use{it.readBytes()};val pcm=ShortArray((bytes.size-44)/2);ByteBuffer.wrap(bytes,44,bytes.size-44).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(pcm)
  var origin=0L;var lastTail=-1L
  SherpaWake(i.targetContext.assets).use{kws ->repeat(2){assertTrue(kws.resetAt(origin));var hits=0
   val all=pcm+ShortArray(32000)
   for(p in all.indices step 320){val f=all.copyOfRange(p,minOf(p+320,all.size));kws.accept(f,f.size)?.let{assertTrue(it>lastTail);assertTrue(kws.matchedStart>=origin);lastTail=it;hits++}}
   assertEquals("one actual model hit per fresh stream",1,hits);origin+=all.size
   repeat(20){assertNull("silence cannot replay previous keyword",kws.accept(ShortArray(320),320));origin+=320}
  }}
 }
}
