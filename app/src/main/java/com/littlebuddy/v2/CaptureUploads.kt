package com.littlebuddy.v2

/** Takes ownership of every batch, including rejected/unposted remainder. Exactly one owner drain.
 * At most one 16000-sample ring may wait; overflow/age is continuity loss, never arbitrary dropping. */
internal class CaptureUploads(private val post:(Runnable)->Boolean, private val now:()->Long,
    private val allowed:()->Boolean,private val consume:(ShortArray,Boolean,Long)->Unit,
    private val failed:()->Unit,private val capacity:Int=16000,private var maxAgeMs:Long=1000) {
    private data class Frame(val pcm:ShortArray,val speech:Boolean,val capturedAt:Long)
    private val queue=ArrayDeque<Frame>()
    private var samples=0
    private var scheduled=false
    private var cancelled=false
    private val drain=Runnable { drain() }
    @Synchronized fun nativeRoom(bytes:Int) {
        require(bytes in 6400..32000);maxAgeMs=1000L+bytes/32
    }
    /** Wait before another native read, bounded below the actual configured native buffer.
     * A stalled owner cannot silently overwrite a full ring or retain unbounded PCM. */
    fun awaitRoom(count:Int,roomMs:Long):Boolean {
        val deadline=System.nanoTime()+roomMs*1_000_000
        synchronized(this) {
            while(!cancelled && allowed() && samples+count>capacity) {
                val left=(deadline-System.nanoTime())/1_000_000
                if(left<=0)return false
                @Suppress("PLATFORM_CLASS_MAPPED_TO_KOTLIN")
                (this as java.lang.Object).wait(minOf(10L,left))
            }
            return !cancelled && allowed()
        }
    }
    private fun signalRoom() {
        @Suppress("PLATFORM_CLASS_MAPPED_TO_KOTLIN")
        (this as java.lang.Object).notifyAll()
    }
    @Synchronized fun cancel() {cancelled=true;clear()}
    private fun clear(){queue.forEach{it.pcm.fill(0)};queue.clear();samples=0;signalRoom()}
    fun offer(batch:List<ShortArray>,speech:Boolean,capturedAt:Long):Boolean {
        var schedule=false;var failure=false
        synchronized(this) {
            val count=batch.sumOf{it.size.toLong()}
            if(cancelled || !allowed() || count>capacity-samples || batch.any{it.isEmpty() || it.size>320}) {
                batch.forEach{it.fill(0)}
                failure=!cancelled && allowed();cancelled=true;clear()
            } else {
                var remaining=count
                batch.forEach { remaining-=it.size;queue.addLast(Frame(it,speech,capturedAt-remaining/16));samples+=it.size }
                if(!scheduled && queue.isNotEmpty()){scheduled=true;schedule=true}
            }
        }
        if(failure)failed()
        if(schedule && !post(drain)) { synchronized(this){cancelled=true;clear();scheduled=false};failed();return false }
        return synchronized(this){!cancelled}
    }
    private fun drain() {
        while(true) {
            val frame=synchronized(this) {
                if(cancelled || !allowed()){clear();scheduled=false;return}
                if(queue.isEmpty()){scheduled=false;return}
                queue.removeFirst().also{samples-=it.pcm.size;signalRoom()}
            }
            try {
                val age=now()-frame.capturedAt
                check(age in 0..maxAgeMs){"capture continuity expired"}
                if(allowed())consume(frame.pcm,frame.speech,frame.capturedAt) else cancel()
            } catch(_:Exception) {cancel();failed()}
            finally {frame.pcm.fill(0)}
        }
    }
}
