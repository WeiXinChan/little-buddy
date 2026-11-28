package com.littlebuddy.v2

import com.littlebuddy.v2.parent.PinDiagnostic

/** Diagnostic-only, owner-thread, one numeric binding. No identity strings/history or business timers. */
internal enum class ClientPhase { PROBE_SENT, ENDPOINT_RECEIVED, SEAL_SENT, OPEN_RECEIVED, BIND_SENT, BOUND_RECEIVED,
    FIRST_AUDIO_ACCEPTED, FIRST_NATIVE_HEAD_PROGRESS, TRACK_BUILT, TRACK_PLAY, TRACK_PARAMS }
internal data class ClientPhaseEvent(val scope:PinDiagnostic.Scope,val phase:ClientPhase,val phaseBootMs:Long,
    val epoch:Long,val revision:Long,val wireRevision:Long=-1,val wireSequence:Long=-1,
    val receivedBootMs:Long=-1,val capturedLastSpeechBootMs:Long=-1,val stream:Int=-1,val accepted:Boolean=true,
    val durationNs:Long=-1,val minBufferBytes:Int=-1,val configuredBufferBytes:Int=-1,val actualBufferFrames:Int=-1,val startThresholdFrames:Int=-1) {
    fun format(monoMs:Long)="mono_ms=$monoMs stage=CLIENT_PHASE phase=${phase.name} phase_boot_ms=$phaseBootMs captured_last_speech_boot_ms=$capturedLastSpeechBootMs received_boot_ms=$receivedBootMs activity=${scope.activity} transport=${scope.transport} capture=${scope.capture} epoch=$epoch revision=$revision wire_revision=$wireRevision wire_seq=$wireSequence stream=$stream accepted=$accepted duration_ns=$durationNs min_buffer_bytes=$minBufferBytes configured_buffer_bytes=$configuredBufferBytes actual_buffer_frames=$actualBufferFrames start_threshold_frames=$startThresholdFrames"
}
internal data class TrackMetric(val phase:ClientPhase,val durationNs:Long,val success:Boolean,
    val minBufferBytes:Int=-1,val configuredBufferBytes:Int=-1,val actualBufferFrames:Int=-1,val startThresholdFrames:Int=-1)
internal object ClientPhasePort {
    @Volatile private var sink:((ClientPhaseEvent)->Unit)?=null
    fun install(value:((ClientPhaseEvent)->Unit)?){sink=value}
    fun enabled()=sink!=null
    fun emit(value:ClientPhaseEvent){try{sink?.invoke(value)}catch(_:Throwable){}}
}
internal class ClientPhases(private val scope:PinDiagnostic.Scope,private val boot:()->Long) {
    data class Key(val epoch:Long,val revision:Long,val stream:Int)
    var bindingKey:Key?=null;private set
    private var audio=false;private var head=false
    fun clear(){bindingKey=null;audio=false;head=false}
    fun event(phase:ClientPhase,epoch:Long,revision:Long,lastSpeech:Long,wireRevision:Long=-1,
              wireSeq:Long=-1,receivedBoot:Long=-1,accepted:Boolean=true) {
        try {if(!ClientPhasePort.enabled()){clear();return}
            ClientPhasePort.emit(ClientPhaseEvent(scope,phase,boot(),epoch,revision,wireRevision,wireSeq,
                receivedBoot,lastSpeech,bindingKey?.takeIf{it.epoch==epoch && it.revision==revision}?.stream ?: -1,accepted))
        }catch(_:Throwable){} // No diagnostic may fail a conversation.
    }
    fun bound(epoch:Long,revision:Long,stream:Int,lastSpeech:Long,receivedBoot:Long) {
        if(!ClientPhasePort.enabled()){clear();return}
        bindingKey=Key(epoch,revision,stream);audio=false;head=false
        event(ClientPhase.BOUND_RECEIVED,epoch,revision,lastSpeech,revision,receivedBoot=receivedBoot)
    }
    private fun matches(epoch:Long,revision:Long,stream:Int)=bindingKey==Key(epoch,revision,stream)
    fun firstAudio(epoch:Long,revision:Long,stream:Int,lastSpeech:Long,receivedBoot:Long) {
        if(!ClientPhasePort.enabled()){clear();return}
        if(audio || !matches(epoch,revision,stream))return
        audio=true;event(ClientPhase.FIRST_AUDIO_ACCEPTED,epoch,revision,lastSpeech,receivedBoot=receivedBoot)
    }
    fun firstHead(epoch:Long,revision:Long,stream:Int,lastSpeech:Long) {
        if(!ClientPhasePort.enabled()){clear();return}
        if(head || !matches(epoch,revision,stream))return
        head=true;event(ClientPhase.FIRST_NATIVE_HEAD_PROGRESS,epoch,revision,lastSpeech)
    }
    fun track(key:Key,metric:TrackMetric,lastSpeech:Long) {
        try {if(!ClientPhasePort.enabled()){clear();return};if(bindingKey!=key)return
            ClientPhasePort.emit(ClientPhaseEvent(scope,metric.phase,boot(),key.epoch,key.revision,
                capturedLastSpeechBootMs=lastSpeech,stream=key.stream,accepted=metric.success,durationNs=metric.durationNs,
                minBufferBytes=metric.minBufferBytes,configuredBufferBytes=metric.configuredBufferBytes,
                actualBufferFrames=metric.actualBufferFrames,startThresholdFrames=metric.startThresholdFrames))
        }catch(_:Throwable){}
    }
}
