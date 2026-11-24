package com.littlebuddy.v2

import org.junit.Assert.*
import org.junit.Test

class NativeEvidenceTest {
    @Test fun requestedStartAndCleanupCannotSatisfyRealReadiness() {
        val startupFailed=NativeEvidence(RecorderProof(session=1,started=true,recording=false,stopped=true,released=true),PlayerProof())
        try{startupFailed.requireRunning();fail()}catch(_:IllegalStateException){}
        val noRead=NativeEvidence(RecorderProof(session=1,started=true,recording=true),PlayerProof(Binding(1,"p",1),100))
        try{noRead.requireRunning();fail()}catch(_:IllegalStateException){}
    }
    @Test fun releaseMustReferToPreviouslyRunningNativeResources() {
        val binding=Binding(1,"p",1)
        val before=NativeEvidence(RecorderProof(7,true,true,320),PlayerProof(binding,50))
        before.requireRunning()
        val closed=NativeEvidence(RecorderProof(7,true,false,320,true,true),PlayerProof(null,50,binding,StopResult(true,true)))
        closed.requireReleased(before)
        try{closed.copy(recorder=closed.recorder.copy(session=8)).requireReleased(before);fail()}catch(_:IllegalStateException){}
        try{closed.copy(player=closed.player.copy(stop=StopResult(true,false))).requireReleased(before);fail()}catch(_:IllegalStateException){}
    }
    @Test fun expiryPrecedesHeadReadWriteAndAck() {
        var time=0L;var reads=0;var writes=0;var acks=0;var released=false
        val native=object:TrackPort {
            override val head:Long get(){reads++;return if(time==0L)0 else 50}
            override fun write(pcm:ShortArray,offset:Int):Int{writes++;return pcm.size-offset}
            override fun play(){};override fun pause(){};override fun mute(){};override fun flush(){};override fun stop(){}
            override fun release(){released=true}
        }
        val p=Playback({native},{time},{acks++});val b=Binding(1,"r97",1)
        p.bind(b);p.enqueue(AudioPacket(b,"a",0,100,ShortArray(100)));p.tick()
        val before=listOf(reads,writes,acks);time=60000
        try{p.tick();fail()}catch(_:IllegalStateException){}
        assertEquals(before,listOf(reads,writes,acks));assertTrue(released);assertNull(p.binding)
    }
}
