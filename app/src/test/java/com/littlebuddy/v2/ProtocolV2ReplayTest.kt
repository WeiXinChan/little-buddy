package com.littlebuddy.v2
import org.junit.Test
import org.junit.Assert.*
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
class ProtocolV2ReplayTest {
 @Test fun sameModelNativeHitsAndRealSyntheticPcmUseProductionBoundary() = replay("native-replay.tsv",12)
 private fun replay(file: String,minimum: Int) {
  val root=listOf(File("src/androidTest/assets/m06-protocol-v2"),File("app/src/androidTest/assets/m06-protocol-v2")).first{it.isDirectory}
  val lines=File(root,file).readLines();var i=0;val failures=mutableListOf<String>();var cases=0
  while(i<lines.size) {
   val c=lines[i++].split('\t');check(c[0]=="case")
   val name=c[1];val managed=c[2]=="true";val expected=if(c[3]=="NONE")emptyList() else c[3].split(",")
   val hits=mutableMapOf<Int,CommandBoundary.Hit>()
   while(i<lines.size && lines[i].startsWith("hit\t")) {val h=lines[i++].split('\t');hits[h[1].toInt()]=CommandBoundary.Hit(h[2],h[3].toLong(),h[4].toLong())}
   var pcm=ShortArray(0)
   for(source in c[4].split(",")) {
    val f=File(root,"$source.wav").takeIf{it.exists()} ?: File(root.parentFile,"m06-commands/$source.wav")
    val bytes=f.readBytes();val part=ShortArray((bytes.size-44)/2)
    ByteBuffer.wrap(bytes,44,bytes.size-44).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(part)
    pcm+=part+ShortArray(32000)
   }
   val bufferedMarker=hits.values.firstOrNull{it.name=="确认退出"}?.end?.plus(1)
   val boundary=CommandBoundary{0L};val results=mutableListOf<String>();val all=pcm+ShortArray(19200)
   for(pos in all.indices step 320) {val f=all.copyOfRange(pos,minOf(pos+320,all.size));boundary.frame(f,f.size,hits[pos/320],managed)?.let{results+=it;if(it=="确认退出提示"){assertTrue(boundary.awaitingPromptCompletion);check(boundary.promptComplete(boundary.confirmationNonce,0,0));boundary.armConfirmation(boundary.confirmationNonce,(if(name=="buffered_old_confirm_rejected")checkNotNull(bufferedMarker) else (pos+f.size).toLong()),0)}}}
   if(results!=expected)failures+="$name expected=$expected actual=$results"
   cases++
  }
  assertEquals("all twelve protocol scenarios must execute",minimum,cases)
  assertEquals(failures.joinToString("; "),emptyList<String>(),failures)
 }
}
