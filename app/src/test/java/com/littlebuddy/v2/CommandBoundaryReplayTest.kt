package com.littlebuddy.v2
import org.junit.Test
import org.junit.Assert.*
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
class CommandBoundaryReplayTest {
 @Test fun sameModelNativeHitsAndRealSyntheticPcmUseProductionBoundary() = replay("native-replay.tsv",40)
 @Test fun denyContextExpiresForIndependentCommands() = replay("deny-pair.tsv",4)
 private fun replay(file: String,minimum: Int) {
  val root=listOf(File("src/androidTest/assets/m06-commands"),File("app/src/androidTest/assets/m06-commands")).first{it.isDirectory}
  val lines=File(root,file).readLines();var i=0;val failures=mutableListOf<String>();var cases=0
  while(i<lines.size) {
   val c=lines[i++].split('\t');check(c[0]=="case")
   val name=c[1];val managed=c[2]=="true";val expected=if(c[3]=="NONE")emptyList() else listOf(c[3])
   val hits=mutableMapOf<Int,CommandBoundary.Hit>()
   while(i<lines.size && lines[i].startsWith("hit\t")) {val h=lines[i++].split('\t');hits[h[1].toInt()]=CommandBoundary.Hit(h[2],h[3].toLong(),h[4].toLong())}
   val bytes=File(root,"$name.wav").readBytes();val pcm=ShortArray((bytes.size-44)/2)
   ByteBuffer.wrap(bytes,44,bytes.size-44).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(pcm)
   val boundary=CommandBoundary();val results=mutableListOf<String>();val all=pcm+ShortArray(19200)
   for(pos in all.indices step 320) {val f=all.copyOfRange(pos,minOf(pos+320,all.size));boundary.frame(f,f.size,hits[pos/320],managed)?.let{results+=it}}
   if(results!=expected)failures+="$name expected=$expected actual=$results"
   cases++
  }
  assertTrue("actual native replay corpus required",cases>=minimum)
  assertEquals(failures.joinToString("; "),emptyList<String>(),failures)
 }
}
