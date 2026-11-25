package com.littlebuddy.v2

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRouting
import android.media.AudioTrack
import android.os.Build
import android.os.Handler

internal class AndroidTrack(handler: Handler,
    private val settings: com.littlebuddy.v2.parent.ParentPlaybackSettings = com.littlebuddy.v2.parent.ParentPlaybackSettings(),
    routeLost: () -> Unit) : TrackPort {
    private val track: AudioTrack
    private var route: Int? = null
    private val listener = AudioRouting.OnRoutingChangedListener { routing ->
        val next = routing.routedDevice?.id
        if (route != null && next != route) routeLost()
        route = next
    }
    init {
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
        } catch (failure: Exception) { track.release(); throw failure }
    }
    override val head get() = track.playbackHeadPosition.toLong() and 0xffffffffL
    override fun write(pcm: ShortArray, offset: Int) =
        track.write(pcm, offset, pcm.size - offset, AudioTrack.WRITE_NON_BLOCKING)
    override fun play() {
        track.play()
        track.playbackParams = android.media.PlaybackParams().setSpeed(settings.rate / 100f).setPitch(1f)
    }
    override fun pause() = track.pause()
    override fun mute() { check(track.setVolume(0f) == AudioTrack.SUCCESS) }
    override fun flush() = track.flush()
    override fun stop() { track.stop(); check(track.playState == AudioTrack.PLAYSTATE_STOPPED) }
    override fun release() {
        track.removeOnRoutingChangedListener(listener)
        track.release()
        check(track.state == AudioTrack.STATE_UNINITIALIZED)
    }
}
