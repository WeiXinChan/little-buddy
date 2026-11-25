package android.os
import java.util.concurrent.ConcurrentLinkedQueue
class Handler {
 val jobs=ConcurrentLinkedQueue<Runnable>()
 fun post(job:Runnable):Boolean {jobs.add(job);return true}
 fun drain() {while(true)(jobs.poll() ?: break).run()}
}
object SystemClock {
 @Volatile var realtime=false
 @Volatile var manualNow=100000L
 fun uptimeMillis()=elapsedRealtime()
 fun elapsedRealtime()=if(realtime)System.nanoTime()/1_000_000 else manualNow
}
