package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
import android.os.Handler
import android.os.SystemClock
import android.media.AudioRecord
import android.content.res.AssetManager
import com.littlebuddy.SherpaWake

/** Real Capture/ledger/bootstrap/lease; controlled native producer and KWS port, NOT ONNX evidence. */
class RecoveryCaptureTest {
    private fun await(test:()->Boolean){val end=System.nanoTime()+3_000_000_000;while(!test() && System.nanoTime()<end)Thread.sleep(3);assertTrue(test())}
    @Test fun realCaptureKeepsPrefixCoordinatesAndSpeechBeforeReadyWithoutNetwork(){
        AudioRecord.reset(21);SherpaWake.detectAfter=10;AbsoluteWake.initializeHook={};AbsoluteWake.rearmHook={}
        val owner=Handler();var connects=0;var failures=0;var accepted:WakeBoundary?=null
        val port=RecoveryHandoff(SystemClock::elapsedRealtime,{owner.post(it)},{true},{connects++;accepted=it},{},{failures++},{})
        val cap=Capture(AssetManager(),owner,port,{true}){failures++};cap.start()
        try {
            await{cap.nativeProof.frames>=21*320};owner.drain()
            assertEquals(1,connects);assertNotNull(accepted);assertTrue(port.retainedSamples()>0)
            val client=VoiceClient();assertTrue(client.received.isEmpty());assertTrue(port.ready(client));owner.drain()
            assertEquals(1,client.wakes.size);assertEquals(accepted!!.boot,client.wakes.single())
            assertEquals("wake",client.order.first());assertTrue(client.received.isNotEmpty());assertEquals(0,failures)
            val sequence=client.received.map{it[0].toInt()};assertEquals((1..21).toList(),sequence)
            assertEquals(0,port.retainedSamples())
        }finally{cap.close();owner.drain();assertTrue(ProcessRecorders.released())}
    }
    @Test fun noWakeRunsOnlyLocalCaptureAndNeverConnects(){
        AudioRecord.reset(30);SherpaWake.detectAfter=100;var connects=0;val owner=Handler()
        val p=RecoveryHandoff(SystemClock::elapsedRealtime,{owner.post(it)},{true},{connects++},{},{},{})
        val cap=Capture(AssetManager(),owner,p,{true}){};cap.start()
        try{await{cap.nativeProof.frames>=30*320};owner.drain();assertEquals(0,connects);assertEquals(0,p.retainedSamples())}
        finally{cap.close();owner.drain();assertTrue(ProcessRecorders.released())}
    }
    @Test fun neverReadyHitsOriginalBoundClearsAndReleases(){
        AudioRecord.reset(200);SherpaWake.detectAfter=1;val owner=Handler();var failures=0
        val p=RecoveryHandoff(SystemClock::elapsedRealtime,{owner.post(it)},{true},{},{},{failures++},{})
        val cap=Capture(AssetManager(),owner,p,{true}){failures++};cap.start()
        try{await{cap.nativeProof.released};owner.drain();assertTrue(failures>0);assertEquals(0,p.retainedSamples())}
        finally{cap.close();owner.drain();assertTrue(ProcessRecorders.released())}
    }
}
