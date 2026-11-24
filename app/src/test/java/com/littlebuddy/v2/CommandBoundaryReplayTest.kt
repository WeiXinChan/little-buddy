package com.littlebuddy.v2
import org.junit.Test
import org.junit.Assert.*
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
class CommandBoundaryReplayTest {
 private val approved=mapOf(
  "negative_pause_cancel_1.6" to "NONE", "negative_pause_exit_1.6" to "NONE",
  "negative_pause_cancel_4.0" to "NONE", "negative_pause_exit_4.0" to "NONE",
  "deny_pair_cancel_4.0" to "取消", "deny_pair_exit_4.0" to "退出管理")
 private val root get()=listOf(File("src/androidTest/assets/m06-commands"),File("app/src/androidTest/assets/m06-commands")).first{it.isDirectory}
 private fun sha(file:File)=java.security.MessageDigest.getInstance("SHA-256").digest(file.readBytes()).joinToString(""){"%02x".format(it)}
 private fun oracle():Map<String,List<String>> {
  val manifest=File(root,"event-oracle-v2.1.tsv")
  assertEquals("reviewed v2.1 manifest; any change requires explicit review", "ddaade9cf6da9be4f5b48378a6ed668485cf38feb6f74a58564f2e49d6ddb276",sha(manifest))
  val lines=manifest.readLines();assertTrue(lines.contains("# event-oracle-version\tv2.1"))
  val rows=lines.filter{it.startsWith("case\t")}.map{it.split('\t')}
  assertEquals(49,rows.size);assertEquals(49,rows.map{it[1]}.toSet().size)
  val original=listOf("native-replay.tsv","deny-pair.tsv").flatMap{file->
   val h=lines.single{it.startsWith("# original-tsv\t$file\t")}.split('\t')[2]
   assertEquals("preserved original TSV $file",h,sha(File(root,file)))
   File(root,file).readLines().filter{it.startsWith("case\t")}.map{it.split('\t')}
  }.associateBy{it[1]}
  assertEquals(original.keys,rows.map{it[1]}.toSet())
  for(r in rows){assertEquals(6,r.size);val old=original.getValue(r[1]);assertEquals(old[2],r[2]);assertEquals(old[3],r[3]);assertEquals("preserved WAV ${r[1]}",r[5],sha(File(root,"${r[1]}.wav")))}
  val changed=rows.filter{it[3]!=it[4]}.associate{it[1] to it[3]}
  assertEquals("exactly the six approved deltas, no expanded allowlist",approved,changed)
  rows.filter{it[1] in approved}.forEach{assertEquals("only change is confirmation prompt","确认退出提示",it[4]);assertEquals("true",it[2])}
  assertEquals(43,rows.count{it[3]==it[4]})
  return rows.associateBy{it[1]}
 }
 @Test fun v21DiffIsExactlySixApprovedPromptOnlyChangesAnd43Unchanged() {oracle()}

 @Test fun sameModelNativeHitsAndRealSyntheticPcmUseProductionBoundary() = replay("native-replay.tsv",45)
 @Test fun denyContextExpiresForIndependentCommands() = replay("deny-pair.tsv",4)
 private fun replay(file: String,required: Int) {
  val versioned=oracle();val observedDifferences=mutableSetOf<String>()
  val lines=File(root,file).readLines();var i=0;val failures=mutableListOf<String>();var cases=0
  while(i<lines.size) {
   val c=lines[i++].split('\t');check(c[0]=="case")
   val name=c[1];val managed=c[2]=="true";val legacy=if(c[3]=="NONE")emptyList() else listOf(c[3]);val v21=versioned.getValue(name)[4];val expected=if(v21=="NONE")emptyList() else listOf(v21)
   val hits=mutableMapOf<Int,CommandBoundary.Hit>()
   while(i<lines.size && lines[i].startsWith("hit\t")) {val h=lines[i++].split('\t');hits[h[1].toInt()]=CommandBoundary.Hit(h[2],h[3].toLong(),h[4].toLong())}
   val bytes=File(root,"$name.wav").readBytes();val pcm=ShortArray((bytes.size-44)/2)
   ByteBuffer.wrap(bytes,44,bytes.size-44).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(pcm)
   val boundary=CommandBoundary{0L};val results=mutableListOf<String>();val all=pcm+ShortArray(19200)
   for(pos in all.indices step 320) {val f=all.copyOfRange(pos,minOf(pos+320,all.size));boundary.frame(f,f.size,hits[pos/320],managed)?.let{results+=it}}
   if(results!=legacy)observedDifferences+=name
   if(managed && (legacy.isEmpty() || name in approved))assertTrue("shared stay-managed invariant $name",results.none{it in listOf("取消","退出管理")})
   println("v2.1 case=$name legacy=$legacy expected=$expected actual=$results legacyMatched=${results==legacy}")
   if(results!=expected)failures+="$name expected=$expected actual=$results"
   cases++
  }
  assertEquals("all original cases must execute",required,cases)
  val expectedDifferences=versioned.keys.filter{it in approved && (if(file=="deny-pair.tsv")it.startsWith("deny_pair_") else !it.startsWith("deny_pair_"))}.toSet()
  assertEquals("actual old-to-v2.1 differences cannot exceed or omit reviewed six",expectedDifferences,observedDifferences)
  assertEquals(failures.joinToString("; "),emptyList<String>(),failures)
 }
}
