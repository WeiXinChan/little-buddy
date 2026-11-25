package com.littlebuddy.v2

import android.annotation.SuppressLint
import android.content.res.AssetManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Handler
import android.os.SystemClock
import com.k2fsa.sherpa.onnx.KeywordSpotter
import com.k2fsa.sherpa.onnx.KeywordSpotterConfig
import com.k2fsa.sherpa.onnx.OnlineModelConfig
import com.k2fsa.sherpa.onnx.OnlineTransducerModelConfig
import java.util.concurrent.atomic.AtomicBoolean

/** Dedicated local two-command detector. It has no VoiceClient, PCM sink, transcript or network port. */
internal class ManagementCapture(private val assets: AssetManager, private val owner: Handler,
    private val allowed: () -> Boolean, private val exit: () -> Unit, private val failed: () -> Unit) {
    private val started=AtomicBoolean(false)
    private val cancelled=AtomicBoolean(false)
    @Volatile private var thread: Thread?=null
    @Volatile private var nativeHandle:AudioRecord?=null
    @Volatile private var lease:RecorderLease?=null
    private val nativeLock=Any()
    private val stopRequested=AtomicBoolean(false)
    @Volatile var quarantined=false; private set
    @Volatile var nativeProof=RecorderProof(); private set
    fun start() {
        check(started.compareAndSet(false,true) && thread==null && !quarantined)
        lease=ProcessRecorders.acquire("management")
        if(lease==null){quarantined=true;owner.post{if(allowed())failed()};return}
        val hold=checkNotNull(lease)
        val worker=Thread({record()},"v2-local-management-kws");thread=worker
        try {worker.start();Thread({worker.join();hold.workerFinished()},"v2-management-join").start()}
        catch(_:Exception){quarantined=true;requestCancel()}
    }
    @SuppressLint("MissingPermission")
    private fun record() {
        var recorder: AudioRecord?=null
        var spotter: KeywordSpotter?=null
        var stream: com.k2fsa.sherpa.onnx.OnlineStream?=null
        val samples=ShortArray(320)
        var attemptedNative=false
        var attemptedModel=false
        var attemptedStream=false
        try {
            if(cancelled.get() || !allowed())return
            attemptedModel=true
            val suffix="epoch-13-avg-2-chunk-16-left-64"
            val keyword=KeywordSpotter(assets,KeywordSpotterConfig(modelConfig=OnlineModelConfig(
                transducer=OnlineTransducerModelConfig(encoder="wake/encoder-$suffix.int8.onnx",
                    decoder="wake/decoder-$suffix.onnx",joiner="wake/joiner-$suffix.int8.onnx"),
                tokens="wake/tokens.txt",modelType="zipformer2",numThreads=1),
                keywordsFile="v2-management/exit-keywords.txt"))
            spotter=keyword;attemptedStream=true;val input=keyword.createStream();stream=input
            val minimum=AudioRecord.getMinBufferSize(16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT)
            check(minimum in 1..32000)
            if(cancelled.get() || !allowed())return
            attemptedNative=true
            val native=AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION,16000,AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,maxOf(minimum,6400)); recorder=native
            synchronized(nativeLock){nativeHandle=native}
            check(native.state==AudioRecord.STATE_INITIALIZED)
            if (cancelled.get() || !allowed()) return
            synchronized(nativeLock){if(cancelled.get() || !allowed())return;native.startRecording()}
            check(native.recordingState==AudioRecord.RECORDSTATE_RECORDING)
            nativeProof=RecorderProof(native.audioSessionId,started=true,recording=true)
            val deadline=SystemClock.elapsedRealtime()+600_000
            while (!cancelled.get() && allowed() && SystemClock.elapsedRealtime()<deadline) {
                val count=native.read(samples,0,samples.size,AudioRecord.READ_NON_BLOCKING)
                if(cancelled.get() || !allowed())break
                check(count in 0..samples.size)
                if (count==0) { Thread.sleep(5); continue }
                nativeProof=nativeProof.copy(frames=nativeProof.frames+count)
                val floats=FloatArray(count) { samples[it]/32768f }
                try {if(cancelled.get() || !allowed())break;input.acceptWaveform(floats,16000)}
                finally{floats.fill(0f);samples.fill(0)}
                if(cancelled.get() || !allowed())break
                while (!cancelled.get() && allowed()) {
                    val ready=keyword.isReady(input)
                    if(cancelled.get() || !allowed() || !ready)break
                    keyword.decode(input)
                    if(cancelled.get() || !allowed())break
                    val result=keyword.getResult(input)
                    if(cancelled.get() || !allowed())break
                    if (result.keyword in setOf("取消","退出管理页面")) {
                        owner.post { if (!cancelled.get() && allowed()) exit() }
                        return
                    }
                }
            }
        } catch (_: Exception) {
            quarantined=true // Constructor/native failure cannot certify that all native state was released.
            if (!cancelled.get()) owner.post { if (allowed()) failed() }
        } finally {
            samples.fill(0)
            var released=!attemptedNative
            synchronized(nativeLock) {
                if(recorder!=null) {
                    try {if(recorder.recordingState==AudioRecord.RECORDSTATE_RECORDING)recorder.stop()
                        check(recorder.recordingState==AudioRecord.RECORDSTATE_STOPPED)
                        nativeProof=nativeProof.copy(recording=false,stopped=true)
                    } catch(_:Exception){quarantined=true}
                    try {recorder.release();check(recorder.state==AudioRecord.STATE_UNINITIALIZED)
                        nativeProof=nativeProof.copy(recording=false,released=true);released=true
                    } catch(_:Exception){quarantined=true}
                }
                nativeHandle=null
            }
            if(released)lease?.nativeReleased()
            var disposed=!attemptedModel || (spotter!=null && (!attemptedStream || stream!=null))
            try {stream?.release()}catch(_:Exception){quarantined=true;disposed=false}
            try {spotter?.release()}catch(_:Exception){quarantined=true;disposed=false}
            if(disposed)lease?.modelsReleased()
        }
    }
    fun requestCancel() {
        cancelled.set(true)
        if(!stopRequested.compareAndSet(false,true))return
        val hold=lease ?: return
        if(!hold.beginStop())return
        Thread({try {synchronized(nativeLock) {
            nativeHandle?.let{if(it.recordingState==AudioRecord.RECORDSTATE_RECORDING)it.stop()}
        }}catch(_:Exception){quarantined=true}finally{hold.endStop()}},"v2-management-stop").start()
    }
    fun close() {
        requestCancel(); val old=thread ?: return
        old.join(500); if (old.isAlive) quarantined=true else {lease?.workerFinished();thread=null}
    }
}
