package android.media
class AudioDeviceInfo(val id:Int=1)
interface AudioRouting {
    val routedDevice: AudioDeviceInfo?
    fun interface OnRoutingChangedListener { fun onRoutingChanged(routing:AudioRouting) }
}
class AudioAttributes { class Builder { fun setUsage(n:Int)=this;fun setContentType(n:Int)=this;fun build()=AudioAttributes() }
    companion object {const val USAGE_MEDIA=1;const val CONTENT_TYPE_SPEECH=1} }
class AudioFormat {class Builder {fun setSampleRate(n:Int)=this;fun setChannelMask(n:Int)=this;fun setEncoding(n:Int)=this;fun build()=AudioFormat()}
    companion object {const val CHANNEL_OUT_MONO=1;const val ENCODING_PCM_16BIT=2} }
class PlaybackParams {fun setSpeed(n:Float)=this;fun setPitch(n:Float)=this}
class AudioTrack:AudioRouting {
    companion object {const val MODE_STREAM=1;const val STATE_INITIALIZED=1;const val STATE_UNINITIALIZED=0
        const val SUCCESS=0;const val WRITE_NON_BLOCKING=1;const val PLAYSTATE_STOPPED=0
        val instances=java.util.concurrent.CopyOnWriteArrayList<AudioTrack>()
        @JvmStatic fun getMinBufferSize(a:Int,b:Int,c:Int)=4800 }
    class Builder {fun setAudioAttributes(a:AudioAttributes)=this;fun setAudioFormat(a:AudioFormat)=this
        fun setTransferMode(n:Int)=this;fun setBufferSizeInBytes(n:Int)=this;fun build()=AudioTrack()}
    init {instances.add(this)}
    var state=STATE_INITIALIZED;var playState=PLAYSTATE_STOPPED
    var playbackHeadPosition=0;var playbackParams=PlaybackParams();override val routedDevice=AudioDeviceInfo()
    var volume=1f;var plays=0;var volumeCalls=0
    fun setVolume(n:Float):Int {volume=n;volumeCalls++;return SUCCESS}
    val bufferSizeInFrames=2400
    private var threshold=2400
    val startThresholdInFrames get()=threshold
    fun setStartThresholdInFrames(n:Int){threshold=n}
    fun addOnRoutingChangedListener(l:AudioRouting.OnRoutingChangedListener,h:android.os.Handler){}
    fun removeOnRoutingChangedListener(l:AudioRouting.OnRoutingChangedListener){}
    fun write(a:ShortArray,off:Int,n:Int,mode:Int):Int {playbackHeadPosition+=n;return n}
    fun play(){plays++;playState=1};fun pause(){playState=2};fun flush(){}
    fun stop(){playState=0};fun release(){state=0}
}
