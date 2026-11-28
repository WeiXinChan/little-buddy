package com.littlebuddy.v2

/** Recorder-owned unanchored prefix. No KWS/upload callback exists. Construct BEFORE native start.
 * Coordinates remain the original read counts; neither the first stamp nor admission rebases them.
 */
internal class CaptureBootstrap(private val ledger:NativeReadLedger) {
    private val closed=java.util.concurrent.atomic.AtomicBoolean(false)
    private val pcm=ShortArray(NativeReadLedger.STARTUP_SAMPLES)
    private val readScratch=ShortArray(320) // Allocate both buffers before native start.
    private var size=0
    private var cursor=0
    private var admitted=false
    var cachedSamplesTotal=0;private set
    var replayPosition=0L;private set
    val pending get()=!closed.get() && admitted && cursor<size
    init {ledger.beginStartup()}
    fun prepare(read:(ShortArray)->Int,allowed:()->Boolean,pause:()->Unit) {
        val frame=readScratch
        fun valid(){check(!closed.get() && allowed()){"capture startup cancelled"}}
        try {
            while(true) {
                valid();ledger.remainingMs();valid()
                if(ledger.startupAnchored){ledger.finishStartup();synchronized(pcm){valid();admitted=true};return}
                val count=try {
                    val n=read(frame);check(n in 0..frame.size){"invalid startup read"}
                    valid();ledger.stageRead(n);valid()
                    synchronized(pcm){
                        valid();check(size+n<=pcm.size){"capture startup cache exhausted"}
                        frame.copyInto(pcm,size,0,n);size+=n;cachedSamplesTotal+=n
                    };n
                }finally{frame.fill(0)}
                if(count==0){pause();valid()}
            }
        }catch(error:Throwable){clear();throw error}
        finally{frame.fill(0)}
    }
    fun take(frame:ShortArray):Int {
        ledger.check() // Never hold the cache monitor across timestamp/native IO.
        return synchronized(pcm) {
        check(admitted && pending)
        val count=minOf(frame.size,size-cursor)
        pcm.copyInto(frame,0,cursor,cursor+count);pcm.fill(0,cursor,cursor+count)
        cursor+=count;replayPosition=cursor.toLong()
        if(cursor==size)pcm.fill(0)
        count
        }
    }
    fun clear(){closed.set(true);synchronized(pcm){pcm.fill(0);size=0;cursor=0;admitted=false}}
}
