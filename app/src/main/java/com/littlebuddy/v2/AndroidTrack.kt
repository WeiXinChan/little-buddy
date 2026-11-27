package com.littlebuddy.v2

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRouting
import android.media.AudioTrack
import android.os.Build
import android.os.Handler

internal class AndroidTrack(handler: Handler,
    private val settings: com.littlebuddy.v2.parent.ParentPlaybackSettings = com.littlebuddy.v2.parent.ParentPlaybackSettings(),
    private val phase:((TrackMetric)->Unit)?=null, routeLost: () -> Unit) : TrackPort {
    private val track: AudioTrack
    private var route: Int? = null
    private var muted=false
    private val listener = AudioRouting.OnRoutingChangedListener { routing ->
        val next = routing.routedDevice?.id
        if (route != null && next != route) routeLost()
        route = next
    }
    init {
        val phaseStart=if(phase!=null)System.nanoTime() else 0L
        val minimum = AudioTrack.getMinBufferSize(24000, AudioFormat.CHANNEL_OUT_MONO,
                                                   AudioFormat.ENCODING_PCM_16BIT)
        check(minimum in 1..48000)
        track = AudioTrack.Builder()
            .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            .setAudioFormat(AudioFormat.Builder().setSampleRate(24000)
                .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
            .setTransferMode(AudioTrack.MODE_STREAM).setBufferSizeInBytes(maxOf(minimum, 4800)).build()
        try {
            check(track.state == AudioTrack.STATE_INITIALIZED)
            check(track.setVolume(settings.volume / 100f) == AudioTrack.SUCCESS)
            if (Build.VERSION.SDK_INT >= 31) track.setStartThresholdInFrames(240)
            track.addOnRoutingChangedListener(listener, handler)
            if(phase!=null)try {
                phase.invoke(TrackMetric(ClientPhase.TRACK_BUILT,System.nanoTime()-phaseStart,true,minimum,maxOf(minimum,4800),
                    track.bufferSizeInFrames,if(Build.VERSION.SDK_INT>=31)track.startThresholdInFrames else -1))
            }catch(_:Throwable){}
        } catch (failure: Exception) { track.release(); throw failure }
    }
    override val head get() = track.playbackHeadPosition.toLong() and 0xffffffffL
    override fun write(pcm: ShortArray, offset: Int) =
        track.write(pcm, offset, pcm.size - offset, AudioTrack.WRITE_NON_BLOCKING)
    override fun play() {
        measured(ClientPhase.TRACK_PLAY) { track.play() }
        measured(ClientPhase.TRACK_PARAMS) { track.playbackParams = android.media.PlaybackParams().setSpeed(settings.rate / 100f).setPitch(1f) }
    }
    private inline fun measured(stage:ClientPhase,block:()->Unit) {
        val before=if(phase!=null)System.nanoTime() else 0L;var success=false
        try{block();success=true}finally{
            if(phase!=null)try{phase.invoke(TrackMetric(stage,System.nanoTime()-before,success))}catch(_:Throwable){}
        }
    }
    override fun pause() = track.pause()
    override fun setVolume(percent: Int): Boolean {
        require(percent in 0..100)
        return muted || track.setVolume(percent/100f)==AudioTrack.SUCCESS
    }
    override fun mute() { muted=true; check(track.setVolume(0f) == AudioTrack.SUCCESS) }
    override fun flush() = track.flush()
    override fun stop() { track.stop(); check(track.playState == AudioTrack.PLAYSTATE_STOPPED) }
    override fun release() {
        track.removeOnRoutingChangedListener(listener)
        track.release()
        check(track.state == AudioTrack.STATE_UNINITIALIZED)
    }
}
