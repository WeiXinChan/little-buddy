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
    private val cancelled=AtomicBoolean(false)
    private var thread: Thread?=null
    @Volatile var quarantined=false; private set
    @Volatile var nativeProof=RecorderProof(); private set
    fun start() {
        check(thread==null && !quarantined)
        thread=Thread({ record() },"v2-local-management-kws").apply { start() }
    }
    @SuppressLint("MissingPermission")
    private fun record() {
        var recorder: AudioRecord?=null
        var spotter: KeywordSpotter?=null
        var stream: com.k2fsa.sherpa.onnx.OnlineStream?=null
        val samples=ShortArray(320)
        try {
            val suffix="epoch-13-avg-2-chunk-16-left-64"
            val keyword=KeywordSpotter(assets,KeywordSpotterConfig(modelConfig=OnlineModelConfig(
                transducer=OnlineTransducerModelConfig(encoder="wake/encoder-$suffix.int8.onnx",
                    decoder="wake/decoder-$suffix.onnx",joiner="wake/joiner-$suffix.int8.onnx"),
                tokens="wake/tokens.txt",modelType="zipformer2",numThreads=1),
                keywordsFile="v2-management/exit-keywords.txt"))
            spotter=keyword; val input=keyword.createStream(); stream=input
            val minimum=AudioRecord.getMinBufferSize(16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT)
            check(minimum in 1..32000)
            val native=AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION,16000,AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,maxOf(minimum,6400)); recorder=native
            check(native.state==AudioRecord.STATE_INITIALIZED)
            if (cancelled.get() || !allowed()) return
            native.startRecording(); check(native.recordingState==AudioRecord.RECORDSTATE_RECORDING)
            nativeProof=RecorderProof(native.audioSessionId,started=true,recording=true)
            val deadline=SystemClock.elapsedRealtime()+600_000
            while (!cancelled.get() && allowed() && SystemClock.elapsedRealtime()<deadline) {
                val count=native.read(samples,0,samples.size,AudioRecord.READ_NON_BLOCKING); check(count>=0)
                if (count==0) { Thread.sleep(5); continue }
                nativeProof=nativeProof.copy(frames=nativeProof.frames+count)
                val floats=FloatArray(count) { samples[it]/32768f }
                input.acceptWaveform(floats,16000); floats.fill(0f); samples.fill(0)
                while (keyword.isReady(input)) {
                    keyword.decode(input)
                    if (keyword.getResult(input).keyword in setOf("取消","退出管理页面")) {
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
            try { stream?.release() } catch (_: Exception) { quarantined=true }
            try { spotter?.release() } catch (_: Exception) { quarantined=true }
            if (recorder!=null) {
                try {
                    if (recorder.recordingState==AudioRecord.RECORDSTATE_RECORDING) recorder.stop()
                    check(recorder.recordingState==AudioRecord.RECORDSTATE_STOPPED)
                    nativeProof=nativeProof.copy(recording=false,stopped=true)
                } catch (_: Exception) { quarantined=true }
                try { recorder.release(); check(recorder.state==AudioRecord.STATE_UNINITIALIZED)
                    nativeProof=nativeProof.copy(recording=false,released=true)
                } catch (_: Exception) { quarantined=true }
            }
        }
    }
    fun close() {
        cancelled.set(true); val old=thread ?: return
        old.join(500); if (old.isAlive) quarantined=true else thread=null
    }
}
