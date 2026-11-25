package android.os
import java.util.concurrent.ConcurrentLinkedQueue
class Handler {
 val jobs=ConcurrentLinkedQueue<Runnable>()
 fun post(job:Runnable):Boolean {jobs.add(job);return true}
 fun drain() {while(true)(jobs.poll() ?: break).run()}
}
object SystemClock {fun elapsedRealtime()=100000L}
