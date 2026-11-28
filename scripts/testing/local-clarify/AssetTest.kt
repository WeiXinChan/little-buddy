package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
import android.content.res.AssetManager
import java.nio.file.Files
import java.nio.file.Path
class LocalClarifyAssetTest {
 private fun bytes()=Files.readAllBytes(Path.of(System.getProperty("clarify.asset")))
 private fun assets(pcm:ByteArray,sha:String="b11fca1d95974735e3f48faf6e8d21d8b8a541c0bf7d4c521c5d10c3f8b260e7")=AssetManager(mapOf("v2-local-clarify.pcm" to pcm,"v2-local-clarify.sha256" to (sha+"\n").toByteArray()))
 @Test fun actualPinnedAssetDecodedWithoutTrimmingAndEachPurposeGetsIndependentPcm(){
  val raw=bytes();val a=ClarificationAsset.load(assets(raw));val b=ClarificationAsset.load(assets(raw))
  try {assertEquals(79200,a.size);assertArrayEquals(a,b)
   for(i in a.indices)assertEquals(((raw[2*i].toInt() and 255) or (raw[2*i+1].toInt() shl 8)).toShort(),a[i])
   a.fill(0);assertTrue(b.any{it!=0.toShort()})
  }finally{raw.fill(0);a.fill(0);b.fill(0)}
 }
 @Test fun changedHashOversizedEmptyAndOddAssetsAreRejected(){
  for(raw in listOf(bytes().also{it[0]=(it[0].toInt() xor 1).toByte()},ByteArray(288002),ByteArray(0),ByteArray(481))){
   var failed=false;try{ClarificationAsset.load(assets(raw))}catch(_:IllegalArgumentException){failed=true}catch(_:IllegalStateException){failed=true}
   finally{raw.fill(0)};assertTrue(failed)
  }
 }
}
