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
  val manifest=inst.context.assets.open("m06-commands/event-oracle-v2.1.tsv").use{it.readBytes()}
  val hash=java.security.MessageDigest.getInstance("SHA-256").digest(manifest).joinToString(""){"%02x".format(it)}
  assertEquals("pinned reviewed v2.1 oracle","ddaade9cf6da9be4f5b48378a6ed668485cf38feb6f74a58564f2e49d6ddb276",hash)
  val rows=manifest.toString(Charsets.UTF_8).lineSequence().filter{it.startsWith("case\t")}.map{it.split('\t')}.toList()
  assertEquals(49,rows.size);assertEquals(43,rows.count{it[3]==it[4]});assertEquals(6,rows.count{it[3]!=it[4]})
  val output=JSONArray();var failures=0
  for(row in rows) {
   val name=row[1];val expected=if(row[4]=="NONE")null else row[4];val managed=row[2]=="true"
   val wav=inst.context.assets.open("m06-commands/$name.wav").use{it.readBytes()}
   assertEquals("preserved WAV $name",row[5],java.security.MessageDigest.getInstance("SHA-256").digest(wav).joinToString(""){"%02x".format(it)})
   val boundary=CommandBoundary();val decisions=mutableListOf<String>();val audio=pcm(name)
   SherpaWake(inst.targetContext.assets,"*","wake/manage.txt",8).use { kws ->
    for(pos in audio.indices step 320) {
     val frame=audio.copyOfRange(pos,minOf(pos+320,audio.size));val tail=kws.accept(frame,frame.size)
     val hit=tail?.let {CommandBoundary.Hit(checkNotNull(kws.detectedKeyword),kws.matchedStart,it)}
     boundary.frame(frame,frame.size,hit,managed)?.let{decisions+=it}
    }
    repeat(60) {val frame=ShortArray(320);val tail=kws.accept(frame,320);boundary.frame(frame,320,tail?.let{CommandBoundary.Hit(checkNotNull(kws.detectedKeyword),kws.matchedStart,it)},managed)?.let{decisions+=it}}
   }
   if(managed && (row[3]=="NONE" || row[3]!=row[4]))assertTrue("shared no-exit invariant $name",decisions.none{it in listOf("取消","退出管理")})
   val passed=decisions==if(expected==null)emptyList<String>() else listOf(expected)
   if(!passed)failures++
   output.put(JSONObject().put("name",name).put("oracle","v2.1").put("legacy_expected",row[3]).put("expected",expected).put("decisions",JSONArray(decisions)).put("passed",passed))
  }
  V2HostFixture.evidenceDirectory().resolve("kws-model-boundary.json").writeText(output.toString(2))
  assertEquals("real same-version KWS + production boundary corpus failures",0,failures)
 }
 @Test fun wakeTailAndManagementSequenceDoNotRepeatInSilence() {
  val decisions=mutableListOf<String>();val boundary=CommandBoundary();var managed=false
  SherpaWake(inst.targetContext.assets,"*","wake/manage.txt",8).use {kws ->
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
