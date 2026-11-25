package android.media
import java.util.concurrent.atomic.AtomicInteger
object AudioFormat {const val CHANNEL_IN_MONO=1;const val ENCODING_PCM_16BIT=2}
object MediaRecorder {object AudioSource {const val VOICE_COMMUNICATION=1;const val VOICE_RECOGNITION=2}}
class AudioRecord(a:Int,b:Int,c:Int,d:Int,e:Int) {
 companion object {
 const val STATE_INITIALIZED=1;const val STATE_UNINITIALIZED=0;const val RECORDSTATE_RECORDING=3;const val RECORDSTATE_STOPPED=1;const val READ_NON_BLOCKING=1
 val active=AtomicInteger();val maximum=AtomicInteger();val made=AtomicInteger()
 @Volatile var frames=21
 var onRead:(Int)->Unit={}
 var beforeConstruct:()->Unit={}
 var beforeStart:()->Unit={}
 var afterStart:()->Unit={}
 fun getMinBufferSize(a:Int,b:Int,c:Int)=6400
 fun reset(n:Int) {check(active.get()==0);frames=n;maximum.set(0);made.set(0);onRead={};beforeConstruct={};beforeStart={};afterStart={}}
 }
 init{beforeConstruct()}
 var state=STATE_INITIALIZED
 var recordingState=RECORDSTATE_STOPPED
 val audioSessionId=made.incrementAndGet()
 private var reads=0
 fun startRecording(){beforeStart();recordingState=RECORDSTATE_RECORDING;val n=active.incrementAndGet();maximum.updateAndGet{maxOf(it,n)};afterStart()}
 fun read(output:ShortArray,offset:Int,count:Int,mode:Int):Int {
  if(recordingState!=RECORDSTATE_RECORDING)return 0
  if(reads>=frames)return 0
  reads++;output.fill(reads.toShort());onRead(reads);return count
 }
 fun stop(){if(recordingState==RECORDSTATE_RECORDING){recordingState=RECORDSTATE_STOPPED;active.decrementAndGet()}}
 fun release(){stop();state=STATE_UNINITIALIZED}
}
