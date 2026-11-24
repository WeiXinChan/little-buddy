package com.littlebuddy
import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import com.littlebuddy.v2.*
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
/** Only dedicated synthetic AVD test APK; main app never implements PCM persistence. */
internal class SyntheticInputProbe(private val a:V2VoiceActivity,private val nonce:String,private val source:ByteArray,private val expectedSha:String) {
 companion object {const val ENTER_SHA="c53eb146203afc87fd8092f60721e49a20d30baaa0811da715788a40fe582e34"}
 private val i=InstrumentationRegistry.getInstrumentation()
 private val sourceConfiguration=a.captureSourceEvidence()
 private val startedMs=SystemClock.elapsedRealtime()
 private val startedNs=System.nanoTime()
 private val storage=ByteArray(128000*2)
 private var used=0
 private var firstFrame=-1L;private var lastFrame=-1L;private var session:Int?=null
 private var endedNs=startedNs;private var closed=false
 private val watermarks=JSONArray();private var nextWatermark=0L
 private var firstRejectedMs:Long?=null;private var firstRejectedFrame:Long?=null
 private var frozenMs:Long?=null
 private val dir=File(i.targetContext.filesDir,"m06/synthetic-$nonce")
 private fun sha(bytes:ByteArray)=java.security.MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02x".format(it)}
 init {
  check(a.syntheticProbeAllowed() && a.syntheticCaptureDiagnostics)
  check(Regex("[a-f0-9-]{36}").matches(nonce))
  check(expectedSha==ENTER_SHA && sha(source)==ENTER_SHA)
  check(source.size==44+64960*2) // authorized immutable fixture, not arbitrary microphone input
  a.syntheticPcmObserver={data,count,proof->accept(data,count,proof)}
 }
 @Synchronized private fun accept(data:ShortArray,count:Int,proof:RecorderProof){
  if(closed)return
  val now=SystemClock.elapsedRealtime()
  if(now-startedMs>=8000 || used>=storage.size){
   if(firstRejectedMs==null){firstRejectedMs=now;firstRejectedFrame=proof.frames}
   return
  }
  check(a.syntheticProbeAllowed())
  val n=minOf(count,(storage.size-used)/2)
  if(session==null){session=proof.session;firstFrame=proof.frames-count}
  check(session==proof.session)
  for(index in 0 until n){val v=data[index].toInt();storage[used++]=v.toByte();storage[used++]=(v shr 8).toByte()}
  lastFrame=proof.frames-count+n;endedNs=System.nanoTime()
  if(now>=nextWatermark && watermarks.length()<34){
   watermarks.put(JSONObject().put("elapsed_ms",now).put("monotonic_ns",endedNs).put("native_session",proof.session).put("native_read_end_frame",proof.frames).put("saved_end_frame",lastFrame).put("saved_samples",used/2))
   nextWatermark=now+250
  }
 }
 @Synchronized fun freeze(){if(frozenMs==null)frozenMs=SystemClock.elapsedRealtime();closed=true;a.syntheticPcmObserver=null}
 fun saveAndReplay(){
  freeze();check(used<=256000)
  dir.mkdirs();val raw=storage.copyOf(used)
  try {
   File(dir,"capture.s16le").writeBytes(raw)
   val report=JSONObject().put("scope","authorized synthetic enter fixture only; not environmental/child audio")
    .put("nonce",nonce).put("source_sha256",expectedSha).put("source_samples",64960).put("capture_sha256",sha(raw))
    .put("source_configuration",sourceConfiguration).put("sample_rate",16000).put("channels",1).put("encoding","signed PCM16 little endian")
    .put("session",session).put("first_frame",firstFrame).put("last_frame",lastFrame).put("samples",used/2)
    .put("armed_elapsed_ms",startedMs).put("armed_monotonic_ns",startedNs).put("last_read_monotonic_ns",endedNs)
    .put("read_watermarks",watermarks).put("first_rejected_elapsed_ms",firstRejectedMs).put("first_rejected_native_frame",firstRejectedFrame).put("frozen_elapsed_ms",frozenMs)
    .put("watermark_scope","observed production read completion; not hardware acquisition timestamps")
    .put("window_limit_ms",8000).put("sample_limit",128000)
    .put("native_format_evidence","SYNTHETIC_CAPTURE NATIVE_FORMAT in activity timeline; requested format recorded here")
   File(dir,"capture.json").writeText(report.toString(2))
   val timeline=JSONArray(a.timelineJson());val formats=JSONArray();val stamps=JSONArray()
   for(n in 0 until timeline.length()){val e=timeline.getJSONObject(n);if(e.getString("event")=="SYNTHETIC_CAPTURE" && e.getString("phase").startsWith("NATIVE_FORMAT"))formats.put(e)}
   for(n in 0 until timeline.length()){val e=timeline.getJSONObject(n);if(e.getString("event")=="SYNTHETIC_CAPTURE" && e.optInt("session",-1)==session && e.getString("phase").startsWith("NATIVE_TIMESTAMP"))stamps.put(e)}
   report.put("actual_native_format_events",formats).put("native_timestamp_events",stamps)
   report.put("source_replay",replay(source.copyOfRange(44,source.size)))
   report.put("capture_replay",replay(raw))
   File(dir,"capture.json").writeText(report.toString(2))
  }finally{storage.fill(0);raw.fill(0)}
 }
 private fun replay(bytes:ByteArray):JSONObject {
  val pcm=ShortArray(bytes.size/2){n->((bytes[n*2].toInt() and 255) or (bytes[n*2+1].toInt() shl 8)).toShort()}
  val hits=JSONArray();val events=JSONArray();val boundary=CommandBoundary{0L}
  val all=pcm+ShortArray(32000)
  try {
   SherpaWake(i.targetContext.assets,"*","wake/manage.txt",8).use{kws->
    for(pos in all.indices step 320){val frame=all.copyOfRange(pos,minOf(pos+320,all.size));val tail=kws.accept(frame,frame.size)
     val hit=tail?.let{CommandBoundary.Hit(checkNotNull(kws.detectedKeyword),kws.matchedStart,it)}
     if(hit!=null)hits.put(JSONObject().put("name",hit.name).put("start",hit.start).put("end",hit.end).put("reported_at",pos+frame.size))
     boundary.frame(frame,frame.size,hit,false)?.let{events.put(it)}
    }
   }
   val hashes=JSONObject();for(name in listOf("encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx","decoder-epoch-13-avg-2-chunk-16-left-64.onnx","joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx","tokens.txt","manage.txt"))hashes.put(name,sha(i.targetContext.assets.open("wake/$name").use{it.readBytes()}))
   return JSONObject().put("engine","same installed Android Sherpa AAR and production SherpaWake/CommandBoundary; offline raw replay")
    .put("paths",8).put("score",1.5).put("threshold",.25).put("trailing",2).put("tail_zero_samples",32000).put("model_hashes",hashes).put("hits",hits).put("events",events)
  }finally{pcm.fill(0);all.fill(0)}
 }
}
