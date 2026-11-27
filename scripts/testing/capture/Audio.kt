package android.media
import java.util.concurrent.atomic.AtomicInteger
object AudioFormat {const val CHANNEL_IN_MONO=1;const val ENCODING_PCM_16BIT=2}
object MediaRecorder {object AudioSource {const val VOICE_COMMUNICATION=1;const val VOICE_RECOGNITION=2}}
class AudioRecord(a:Int,b:Int,c:Int,d:Int,e:Int) {
 companion object {
 const val SUCCESS=0
 const val ERROR_INVALID_OPERATION=-3
 const val STATE_INITIALIZED=1;const val STATE_UNINITIALIZED=0;const val RECORDSTATE_RECORDING=3;const val RECORDSTATE_STOPPED=1;const val READ_NON_BLOCKING=1
 val active=AtomicInteger();val maximum=AtomicInteger();val made=AtomicInteger()
 @Volatile var frames=21
 @Volatile var continuous=false
 val overwritten=AtomicInteger()
 @Volatile var producer:Thread?=null
 @Volatile var droppedAfterRead=false
 @Volatile var captureOriginNs=0L
 @Volatile var capturedFrames=0L
 @Volatile var timestampDelayMs=0L
 @Volatile var stampAvailableAfterMs=0L
 var onRead:(Int)->Unit={}
 var beforeTimestamp:()->Unit={}
 var beforeConstruct:()->Unit={}
 var beforeStart:()->Unit={}
 var afterStart:()->Unit={}
 fun getMinBufferSize(a:Int,b:Int,c:Int)=6400
 fun reset(n:Int) {check(active.get()==0);frames=n;timestampDelayMs=0;stampAvailableAfterMs=0;continuous=false;overwritten.set(0);droppedAfterRead=false;android.os.SystemClock.realtime=false;android.os.SystemClock.manualNow=100000;maximum.set(0);made.set(0);onRead={};beforeTimestamp={};beforeConstruct={};beforeStart={};afterStart={}}
 }
 init{beforeConstruct()}
 var state=STATE_INITIALIZED
 var recordingState=RECORDSTATE_STOPPED
 val audioSessionId=made.incrementAndGet()
 private var reads=0
 private val nativeBuffer=java.util.ArrayDeque<Short>()
 @Volatile private var running=false
 private val capacity=e/2
 private var sampleCounter=0
 private var stampFrames=0L
 private var stampTime=0L
 private fun startProducer() {
  if(!continuous)return
  running=true
  val worker=Thread({
   val origin=System.nanoTime();captureOriginNs=origin;var produced=0L
   while(running) {
    val due=(System.nanoTime()-origin)*16000/1_000_000_000
    synchronized(nativeBuffer) {
     while(produced<due){
      if(nativeBuffer.size==capacity){nativeBuffer.removeFirst();overwritten.incrementAndGet()}
      nativeBuffer.addLast((++sampleCounter).toShort());produced++;capturedFrames=produced
      stampFrames=produced;stampTime=origin+produced*1_000_000_000/16000
     }
    }
    Thread.sleep(1)
   }
  },"continuous-native-substitute")
  producer=worker;worker.start()
 }
 fun startRecording(){beforeStart();stampFrames=0;stampTime=android.os.SystemClock.uptimeMillis()*1_000_000;captureOriginNs=stampTime;recordingState=RECORDSTATE_RECORDING;val n=active.incrementAndGet();maximum.updateAndGet{maxOf(it,n)};startProducer();afterStart()}
 fun read(output:ShortArray,offset:Int,count:Int,mode:Int):Int {
  if(recordingState!=RECORDSTATE_RECORDING)return 0
  if(continuous) {
   val size=synchronized(nativeBuffer) {
    val n=minOf(count,nativeBuffer.size)
    repeat(n){output[offset+it]=nativeBuffer.removeFirst()};n
   }
   if(size>0){reads++;onRead(reads)}
   return size
  }
  if(reads>=frames)return 0
  reads++;android.os.SystemClock.manualNow+=count/16;stampFrames+=count;stampTime=android.os.SystemClock.uptimeMillis()*1_000_000;output.fill(reads.toShort());onRead(reads);return count
 }
 fun getTimestamp(out:AudioTimestamp,timebase:Int):Int {
  beforeTimestamp()
  val delay=timestampDelayMs;timestampDelayMs=0;if(delay>0)Thread.sleep(delay)
  if(android.os.SystemClock.uptimeMillis()-captureOriginNs/1_000_000<stampAvailableAfterMs)return ERROR_INVALID_OPERATION
  synchronized(nativeBuffer){out.framePosition=stampFrames;out.nanoTime=stampTime}
  return SUCCESS
 }
 fun stop(){running=false;producer?.join(1000);if(recordingState==RECORDSTATE_RECORDING){recordingState=RECORDSTATE_STOPPED;active.decrementAndGet()}}
 fun release(){stop();state=STATE_UNINITIALIZED}
}

class AudioTimestamp {var framePosition=0L;var nanoTime=0L;companion object{const val TIMEBASE_MONOTONIC=0}}
