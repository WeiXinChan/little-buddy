package com.littlebuddy.v2

import com.littlebuddy.v2.parent.PinDiagnostic
import com.littlebuddy.v2.parent.ConfigurationEventBudget
import org.junit.Assert.*
import org.junit.After
import org.junit.Test

class ClientPhasesTest {
    private val seen=mutableListOf<ClientPhaseEvent>()
    private val phases=ClientPhases(PinDiagnostic.Scope(10,20,0)){5000L}
    private fun enable(){ClientPhasePort.install{seen.add(it)}}
    @After fun clean(){ClientPhasePort.install(null)}
    @Test fun disabledDoesNotKeepBindingOrCallClock(){
        val p=ClientPhases(PinDiagnostic.Scope()){error("diagnostic clock must stay unused")}
        p.bound(1,1,1,100,101);p.firstAudio(1,1,1,100,101);p.firstHead(1,1,1,100)
        assertNull(p.bindingKey);assertTrue(seen.isEmpty())
    }
    @Test fun firstAudioAndNativeHeadAreOncePerCurrentBinding(){
        enable();phases.bound(1,2,3,2000,2100)
        repeat(61){phases.firstAudio(1,2,3,2000,2200);phases.firstHead(1,2,3,2000)}
        assertEquals(1,seen.count{it.phase==ClientPhase.FIRST_AUDIO_ACCEPTED})
        assertEquals(1,seen.count{it.phase==ClientPhase.FIRST_NATIVE_HEAD_PROGRESS})
        phases.bound(1,3,4,3000,3100)
        phases.firstAudio(1,2,3,2000,2200);phases.firstHead(1,2,3,2000)
        phases.firstAudio(1,3,4,3000,3200);phases.firstHead(1,3,4,3000)
        assertEquals(2,seen.count{it.phase==ClientPhase.FIRST_AUDIO_ACCEPTED})
        assertEquals(4,seen.last().stream)
    }
    @Test fun oldTrackCallbackAndClearedPageHaveNoCurrentObservation(){
        enable();phases.bound(1,1,1,100,101);val old=phases.bindingKey!!
        phases.bound(2,1,2,200,201);val count=seen.size
        phases.track(old,TrackMetric(ClientPhase.TRACK_PLAY,20,true),100)
        assertEquals(count,seen.size);phases.clear();phases.firstHead(2,1,2,200);assertEquals(count,seen.size)
    }
    @Test fun endpointRejectionIsExplicitAndDoesNotClaimOldRevisionAccepted(){
        enable();phases.event(ClientPhase.ENDPOINT_RECEIVED,2,4,3000,wireRevision=3,receivedBoot=4000,accepted=false)
        val e=seen.single();assertEquals(4L,e.revision);assertEquals(3L,e.wireRevision);assertFalse(e.accepted)
    }
    @Test fun capturedLastSpeechIsTheOriginalGateBoundaryNotDiagnosticNow(){
        var now=1000L;val gate=InputGate(Waits(),{now},{},{},{},{},{},{})
        gate.wake();gate.speech(900);gate.quiet();now=1200
        assertEquals(900L,gate.capturedLastSpeechBootMs);enable()
        phases.event(ClientPhase.PROBE_SENT,0,gate.revision,gate.capturedLastSpeechBootMs,wireSeq=7)
        assertEquals(900L,seen.single().capturedLastSpeechBootMs);assertEquals(5000L,seen.single().phaseBootMs)
    }
    @Test fun closedNumericVocabularyAndClockNamesAreUnambiguous(){
        enable();phases.event(ClientPhase.PROBE_SENT,1,2,4000,wireSeq=7,receivedBoot=4800)
        val fields=seen.single().format(9999).split(' ').associate{val p=it.split('=',limit=2);p[0] to p[1]}
        assertEquals(setOf("mono_ms","stage","phase","phase_boot_ms","captured_last_speech_boot_ms","received_boot_ms","activity","transport","capture","epoch","revision","wire_revision","wire_seq","stream","accepted","duration_ns","min_buffer_bytes","configured_buffer_bytes","actual_buffer_frames","start_threshold_frames"),fields.keys)
        assertTrue(fields.values.all{it.matches(Regex("[A-Z_]+|true|false|-?[0-9]+"))})
        assertEquals("9999",fields["mono_ms"]);assertEquals("5000",fields["phase_boot_ms"])
    }
    @Test fun phaseFloodCannotSpendCriticalOrOperationReservations(){
        for(config in listOf(false,true)){
            val b=ConfigurationEventBudget(config)
            val phase=(1..1000).count{b.phase()};val general=(1..1000).count{b.general()}
            val configRows=if(config)(1..1000).count{b.configuration()} else 0
            val critical=(1..1000).count{b.critical()};val op=(1..1000).count{b.operation()}
            assertEquals(48,phase);assertEquals(16,critical);assertEquals(32,op)
            assertEquals(256,phase+general+configRows+critical+op)
        }
    }
    @Test fun throwingObserverCannotAlterBusinessCaller(){
        ClientPhasePort.install{error("observer only")}
        phases.bound(1,1,1,100,101);phases.firstAudio(1,1,1,100,102);phases.firstHead(1,1,1,100)
        phases.track(phases.bindingKey!!,TrackMetric(ClientPhase.TRACK_PARAMS,10,false),100)
        ClientPhasePort.install(null);phases.event(ClientPhase.SEAL_SENT,1,1,100);assertNull(phases.bindingKey)
    }
}
