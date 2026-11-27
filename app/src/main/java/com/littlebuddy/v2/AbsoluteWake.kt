package com.littlebuddy.v2

import android.content.res.AssetManager
import com.littlebuddy.WakeKeyword
import java.io.File
import java.nio.ByteBuffer

/** V2-only source-patched keyword core via owned JNI. One recorder worker owns creation, calls and release.
 * Cancellation never disposes an in-flight JNI worker; existing recorder lease remains held. */
internal class AbsoluteWake(private val assets:AssetManager,private val directory:File?,private val allowed:()->Boolean):WakeKeyword {
    private var context:ByteBuffer?=null
    private var initialized=false
    private var closed=false
    private var fed=0L
    /** Caller records this owner before creation so every partial/cancel path can close it. */
    fun initialize() {
        check(!initialized && !closed && context==null)
        if(!allowed())return
        val paths=V2WakeFiles.prepare(assets,checkNotNull(directory),allowed)
        if(!allowed())return
        V2KwsNative.load()
        val size=V2KwsNative.contextBytes();check(size in 16..128)
        val storage=ByteBuffer.allocateDirect(size);context=storage
        check(V2KwsNative.create(storage,paths))
        initialized=true
    }
    /** New feature/decoder origin, same already-loaded model. Worker-only; never called across JNI. */
    fun rearm() {
        check(initialized && !closed)
        if(!allowed())return
        V2KwsNative.newStream(checkNotNull(context))
        fed=0L
    }
    override fun accept(samples:ShortArray,count:Int):Long? {
        check(!closed);require(count in 1..minOf(320,samples.size))
        if(!allowed())return null
        check(initialized)
        val storage=checkNotNull(context)
        V2KwsNative.feed(storage,samples,count)
        fed=Math.addExact(fed,count.toLong())
        if(!allowed())return null
        var steps=0
        while(allowed()) {
            val ready=V2KwsNative.ready(storage)
            if(!allowed() || !ready)return null
            check(++steps<=8) {"keyword decode step bound"}
            val result=V2KwsNative.decode(storage)
            // Validate an observed result before cancellation can discard its invalid coordinates.
            val tail=result?.let {
                try {check(it.size==2);KeywordTail.sample(it[0],it[1],fed)} finally {it.fill(0.0)}
            }
            if(!allowed())return null
            if(tail!=null)return tail
        }
        return null
    }
    override fun close() {
        if(closed)return
        context?.let {storage->
            V2KwsNative.close(storage)
            for(i in 0 until storage.capacity())storage.put(i,0)
            context=null
        }
        closed=true
    }
}
internal object V2KwsNative {
    private var loaded=false
    @Synchronized fun load() {
        if(loaded)return
        try {System.loadLibrary("wali-v2-kws");loaded=true}
        catch(_:LinkageError){throw IllegalStateException("V2 KWS library unavailable")}
    }
    external fun contextBytes():Int
    external fun create(context:ByteBuffer,paths:Array<String>):Boolean
    external fun newStream(context:ByteBuffer)
    external fun feed(context:ByteBuffer,samples:ShortArray,count:Int)
    external fun ready(context:ByteBuffer):Boolean
    external fun decode(context:ByteBuffer):DoubleArray?
    external fun close(context:ByteBuffer)
}
