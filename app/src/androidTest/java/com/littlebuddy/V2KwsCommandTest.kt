package com.littlebuddy
import androidx.test.platform.app.InstrumentationRegistry
import com.littlebuddy.v2.CommandBoundary
import org.junit.Test
import org.junit.Assert.*
import org.json.JSONObject
import org.json.JSONArray
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.io.File
class V2KwsCommandTest {
 private val inst get()=InstrumentationRegistry.getInstrumentation()
 private fun pcm(name: String): ShortArray {
  val bytes=inst.context.assets.open("m06-commands/$name.wav").use{it.readBytes()}
  return ShortArray((bytes.size-44)/2).also{ByteBuffer.wrap(bytes,44,bytes.size-44).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(it)}
 }
 @Test fun actualModelCompleteCommandsAndVariants() {
  val rows=JSONObject(inst.context.assets.open("m06-commands/cases.json").bufferedReader().use{it.readText()}).getJSONArray("cases")
  val output=JSONArray();var failures=0
  for(i in 0 until rows.length()) {
   val row=rows.getJSONObject(i);val name=row.getString("name");val expected=if(row.isNull("expected"))null else row.getString("expected")
   val boundary=CommandBoundary();val decisions=mutableListOf<String>();val audio=pcm(name)
   SherpaWake(inst.targetContext.assets,"*","wake/manage.txt").use { kws ->
    for(pos in audio.indices step 320) {
     val frame=audio.copyOfRange(pos,minOf(pos+320,audio.size));val tail=kws.accept(frame,frame.size)
     val hit=tail?.let {CommandBoundary.Hit(checkNotNull(kws.detectedKeyword),kws.matchedStart,it)}
     boundary.frame(frame,frame.size,hit,row.getBoolean("managed"))?.let{decisions+=it}
    }
    repeat(60) {val frame=ShortArray(320);val tail=kws.accept(frame,320);boundary.frame(frame,320,tail?.let{CommandBoundary.Hit(checkNotNull(kws.detectedKeyword),kws.matchedStart,it)},row.getBoolean("managed"))?.let{decisions+=it}}
   }
   val passed=decisions==if(expected==null)emptyList<String>() else listOf(expected)
   if(!passed)failures++
   output.put(JSONObject().put("name",name).put("expected",expected).put("decisions",JSONArray(decisions)).put("passed",passed))
  }
  File(inst.targetContext.filesDir,"m06").mkdirs();File(inst.targetContext.filesDir,"m06/kws-model-boundary.json").writeText(output.toString(2))
  assertEquals("real same-version KWS + production boundary corpus failures",0,failures)
 }
 @Test fun wakeTailAndManagementSequenceDoNotRepeatInSilence() {
  val decisions=mutableListOf<String>();val boundary=CommandBoundary();var managed=false
  SherpaWake(inst.targetContext.assets,"*","wake/manage.txt").use {kws ->
   for(name in listOf("enter","cancel","exit","enter","exit")) {
    val data=pcm(name)+ShortArray(64000)
    for(pos in data.indices step 320) {
     val frame=data.copyOfRange(pos,minOf(pos+320,data.size));val tail=kws.accept(frame,frame.size)
     boundary.frame(frame,frame.size,tail?.let{CommandBoundary.Hit(checkNotNull(kws.detectedKeyword),kws.matchedStart,it)},managed)?.let {decisions+=it;managed=it=="进入管理"}
    }
   }
  }
  assertEquals(listOf("进入管理","取消","进入管理","退出管理"),decisions)
  val tails=mutableListOf<Long>();var position=0L
  SherpaWake(inst.targetContext.assets).use {kws ->
   repeat(2){val data=pcm("wake")+ShortArray(64000);for(pos in data.indices step 320){val f=data.copyOfRange(pos,minOf(pos+320,data.size));position+=f.size;kws.accept(f,f.size)?.let{assertTrue(it in 0..position);tails+=it}}}
  }
  assertEquals(2,tails.size);assertTrue(tails[1]>tails[0])
 }
}
