package android.os

import java.util.concurrent.ScheduledThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.ConcurrentHashMap

/** JVM-only serial owner port. It is not an Android Looper/device execution claim. */
class Handler {
    private val executor=ScheduledThreadPoolExecutor(1)
    private val tasks=ConcurrentHashMap<Runnable,java.util.concurrent.ScheduledFuture<*>>()
    fun post(task: Runnable): Boolean { executor.execute(task); return true }
    fun postDelayed(task: Runnable, delay: Long): Boolean {
        tasks[task]=executor.schedule(task,delay,TimeUnit.MILLISECONDS); return true
    }
    fun removeCallbacks(task: Runnable) { tasks.remove(task)?.cancel(false) }
    fun close() { executor.shutdownNow() }
}
object SystemClock { @JvmStatic fun elapsedRealtime(): Long=System.nanoTime()/1_000_000 }
