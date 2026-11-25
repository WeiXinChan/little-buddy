package android.os
import java.util.concurrent.*
object Build {object VERSION {@JvmField val SDK_INT=36}}
class Looper {companion object {@JvmStatic fun getMainLooper()=Looper()}}
class Handler(looper:Looper?=null) {
    companion object { val instances=java.util.concurrent.CopyOnWriteArrayList<Handler>() }
    init { instances.add(this) }
    fun pendingCallbacks()=tasks.values.count{!it.isDone && !it.isCancelled}
    private val executor=ScheduledThreadPoolExecutor(1) {r->Thread(r).apply{isDaemon=true}}
    private val tasks=ConcurrentHashMap<Runnable,ScheduledFuture<*>>()
    fun post(r:Runnable):Boolean{executor.execute(r);return true}
    fun postDelayed(r:Runnable,d:Long):Boolean{tasks[r]=executor.schedule(r,d,TimeUnit.MILLISECONDS);return true}
    fun removeCallbacks(r:Runnable){tasks.remove(r)?.cancel(false)}
    fun close(){executor.shutdownNow()}
}
object SystemClock {@JvmStatic fun elapsedRealtime()=System.nanoTime()/1_000_000}
