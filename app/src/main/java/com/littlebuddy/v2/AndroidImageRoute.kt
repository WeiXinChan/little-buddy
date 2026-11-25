package com.littlebuddy.v2

import android.app.Activity
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.View
import android.widget.ImageView
import org.json.JSONArray
import java.security.MessageDigest
import java.util.concurrent.Executor
import java.util.concurrent.atomic.AtomicInteger

/** One private decoded slot. IO/decode runs off the audio/UI owners; publication rechecks the ticket. */
internal class AndroidImageRoute(private val activity: Activity, private val worker: Executor,
                                 private val image: ImageView) : ImagePort {
    private val main=Handler(Looper.getMainLooper())
    private val gate=ImageGate<Bitmap>(SystemClock::elapsedRealtime, { bitmap ->
        activity.runOnUiThread { if(!bitmap.isRecycled)bitmap.recycle() }
    }) { activity.runOnUiThread { render() } }
    private val assembly=PngAssembly(SystemClock::elapsedRealtime)
    private var pendingReady: ImageReady?=null
    private var pendingTicket=0L
    private class Job(val bytes: ByteArray) {
        val state=AtomicInteger(0)
        fun cancel() { if(state.compareAndSet(0,2))bytes.fill(0) }
    }
    private var job: Job?=null
    private val enabled=java.util.concurrent.atomic.AtomicBoolean(false)
    @Synchronized private fun tick() {
        if(assembly.expired()) { assembly.clear();pendingReady=null;gate.failed(pendingTicket) };gate.tick()
        if(job!=null && !gate.isCurrent(pendingTicket)) { job?.cancel();job=null }
    }
    private val clock=object:Runnable {
        override fun run() { if(!enabled.get())return;tick();if(enabled.get() && gate.hasMaterial())main.postDelayed(this,50) else enabled.set(false) }
    }
    private fun schedule() { main.post {
        // Serialize arm/disarm with the actual UI clock; a stale queued callback can only inspect current state.
        main.removeCallbacks(clock)
        enabled.set(gate.hasMaterial())
        if(enabled.get())main.post(clock)
    } }
    private fun render(): Unit=gate.render { bitmap ->
        image.setImageBitmap(bitmap);image.visibility=if(bitmap==null)View.GONE else View.VISIBLE
    }
    @Synchronized override fun bind(scope: ImageScope) { gate.bind(scope);schedule() }
    @Synchronized override fun clear() {
        enabled.set(false);assembly.clear();pendingReady=null;job?.cancel();job=null;gate.clear();main.removeCallbacks(clock)
    }
    @Synchronized override fun outputRevoked() {
        enabled.set(false);assembly.clear();pendingReady=null;job?.cancel();job=null
        gate.outputRevoked();main.removeCallbacks(clock)
    }
    @Synchronized override fun inputChanged() {
        assembly.clear();pendingReady=null;job?.cancel();job=null;gate.inputChanged();schedule()
    }
    override fun acknowledged(player: String, stream: Int, segment: String, end: Long)=gate.acknowledged(player,stream,segment,end)
    override fun expired(value: ImageReady, retainMs: Long) { gate.expired(value,retainMs);schedule() }
    override fun reveal(value: ImageReveal) { gate.reveal(value);schedule() }
    override fun display(value: ImageReveal, action: String, durationMs: Long, retainMs: Long) {
        gate.display(value,action,durationMs,retainMs);schedule()
    }
    @Synchronized override fun begin(value: ImageReady, bytes: Int, chunks: Int, chunkBytes: Int, retainMs: Long) {
        assembly.clear();job?.cancel();job=null
        val ticket=gate.prepare(value,retainMs) ?: return
        try { assembly.begin(value,ticket,bytes,chunks,chunkBytes,retainMs)
            pendingReady=value;pendingTicket=ticket;schedule()
        } catch(f:Exception) { pendingReady=null;gate.failed(ticket);throw f }
    }
    @Synchronized override fun chunk(value: ImageReady, index: Int, offset: Int, data: ByteArray) {
        try { require(value==pendingReady && gate.isCurrent(pendingTicket));assembly.chunk(value,index,offset,data) }
        catch(f:Exception) { data.fill(0);assembly.clear();pendingReady=null;gate.failed(pendingTicket);throw f }
    }
    override fun ready(value: ImageReady)=readyV2(value,15000)
    @Synchronized override fun readyV2(value: ImageReady, retainMs: Long) {
        if(value.source=="dynamic") {
            val complete=try { require(value==pendingReady);assembly.finish(value) }
                catch(f:Exception) { pendingReady=null;gate.failed(pendingTicket);throw f }
            pendingReady=null;decode(complete.ticket,value,complete.bytes,true)
        } else {
            require(value.source=="default")
            val ticket=gate.prepare(value,retainMs) ?: return
            try { worker.execute {
                if(!gate.isCurrent(ticket))return@execute
                val bytes=runCatching { staticBytes(value) }.getOrNull()
                if(bytes==null)gate.failed(ticket) else decodeOnWorker(ticket,value,bytes,false)
            } } catch(_:java.util.concurrent.RejectedExecutionException) { gate.failed(ticket) }
        }
        schedule()
    }
    @Synchronized private fun decode(ticket: Long, value: ImageReady, bytes: ByteArray, dynamic: Boolean) {
        val task=Job(bytes);job?.cancel();job=task
        try { worker.execute {
            if(!task.state.compareAndSet(0,1))return@execute
            try { decodeOnWorker(ticket,value,bytes,dynamic) } finally { bytes.fill(0);task.state.set(2) }
        } } catch(_:java.util.concurrent.RejectedExecutionException) { task.cancel();gate.failed(ticket) }
    }
    private fun decodeOnWorker(ticket: Long, value: ImageReady, bytes: ByteArray, dynamic: Boolean) {
        var result: Bitmap?=null
        try {
            if(!gate.isCurrent(ticket))return
            require(bytes.size<=2_097_152 && MessageDigest.getInstance("SHA-256").digest(bytes)
                .joinToString(""){"%02x".format(it)}==value.asset.sha256)
            if(dynamic)PngAssembly.validate(bytes,value.asset.width,value.asset.height)
            val bounds=BitmapFactory.Options().apply { inJustDecodeBounds=true;inScaled=false }
            BitmapFactory.decodeByteArray(bytes,0,bytes.size,bounds)
            require(bounds.outWidth==value.asset.width && bounds.outHeight==value.asset.height && bounds.outMimeType=="image/png")
            if(!gate.isCurrent(ticket))return
            result=checkNotNull(BitmapFactory.decodeByteArray(bytes,0,bytes.size,BitmapFactory.Options().apply { inScaled=false }))
            require(result.width==value.asset.width && result.height==value.asset.height)
            gate.loaded(ticket,result);result=null
        } catch(_:Exception) { gate.failed(ticket) }
        finally { result?.let { bitmap-> activity.runOnUiThread { bitmap.recycle() } };bytes.fill(0) }
    }
    private fun staticBytes(value: ImageReady): ByteArray {
        require(value.asset.id.matches(Regex("[a-z0-9-]{1,64}")) && value.asset.width==512 && value.asset.height==512)
        val manifest=activity.assets.open("v2-default/manifest.json").use { JSONArray(it.bufferedReader().readText()) }
        require(manifest.length()==60)
        val entry=(0 until manifest.length()).map{manifest.getJSONObject(it)}.single{it.getString("id")==value.asset.id}
        require(entry.getString("png_sha256")==value.asset.sha256 && entry.getInt("width")==512 && entry.getInt("height")==512)
        return activity.assets.open("v2-default/png/${value.asset.id}.png").use { input ->
            val out=java.io.ByteArrayOutputStream();val buffer=ByteArray(8192)
            while(true) { val n=input.read(buffer);if(n<0)break;require(out.size()+n<=1_048_576);out.write(buffer,0,n) }
            out.toByteArray()
        }
    }
}
