package com.littlebuddy.v2

import android.os.Handler
import com.littlebuddy.v2.parent.PinDiagnostic
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Actual VoiceClient/Playback/AndroidTrack source with JVM platform ports, real TLS peer. */
fun main(args:Array<String>) {
    Thread.setDefaultUncaughtExceptionHandler{_,_->System.err.println("PHASE_FIXTURE_UNCAUGHT");kotlin.system.exitProcess(1)}
    val enabled=args[1]=="on";val owner=Handler();val done=CountDownLatch(1)
    val seen=java.util.concurrent.CopyOnWriteArrayList<ClientPhaseEvent>()
    val failures=java.util.concurrent.atomic.AtomicInteger()
    var captured=0L;var audible=0
    if(enabled)ClientPhasePort.install{seen.add(it)}
    lateinit var client:VoiceClient
    client=VoiceClient(owner,{},{},{_,_->},failed={failures.incrementAndGet();done.countDown()},
        diagnosticScope=PinDiagnostic.Scope(10,20,0),requiredContract=ReleaseCompatibility.CONTRACT,
        ready={
            client.wake();captured=android.os.SystemClock.elapsedRealtime()-250
            client.frame(ShortArray(320),true,captured);client.quiet()
        },actualOutput={playing->if(playing){audible++;owner.postDelayed({done.countDown()},100)}})
    owner.post{client.connect(args[0],"A".repeat(32))}
    try{
        check(done.await(5,TimeUnit.SECONDS));check(failures.get()==0);check(audible>0)
        if(enabled){
            val kinds=seen.map{it.phase}
            for(kind in ClientPhase.entries)check(kinds.count{it==kind}==if(kind==ClientPhase.ENDPOINT_RECEIVED)2 else 1){"phase count $kind"}
            val probe=seen.single{it.phase==ClientPhase.PROBE_SENT}
            check(probe.capturedLastSpeechBootMs==captured && probe.phaseBootMs-captured>=300)
            val endpoint=seen.filter{it.phase==ClientPhase.ENDPOINT_RECEIVED}
            check(!endpoint[0].accepted && endpoint[0].wireRevision==0L && endpoint[0].revision==1L)
            check(endpoint[1].accepted && endpoint[1].wireRevision==1L)
            check(seen.filter{it.phase in setOf(ClientPhase.FIRST_AUDIO_ACCEPTED,ClientPhase.FIRST_NATIVE_HEAD_PROGRESS)}.all{it.stream==1 && it.revision==1L && it.epoch==0L})
            val track=seen.single{it.phase==ClientPhase.TRACK_BUILT}
            check(track.minBufferBytes==4800 && track.configuredBufferBytes==4800 && track.actualBufferFrames==2400 && track.startThresholdFrames==240)
            check(seen.all{it.scope==PinDiagnostic.Scope(10,20,0) && it.phaseBootMs>=captured})
            check(seen.filter{it.receivedBootMs>=0}.all{it.receivedBootMs<=it.phaseBootMs})
            println("REAL_PHASE enabled=true phases=${seen.size} rejected_endpoint=1 audio=1 native_head=1 wrong_binding_not_counted=true captured_boundary_preserved=true")
        }else{check(seen.isEmpty());println("REAL_PHASE enabled=false unchanged_audio=true diagnostic_events=0")}
    }finally{
        val closed=CountDownLatch(1);owner.post{client.close();closed.countDown()};check(closed.await(1,TimeUnit.SECONDS))
        owner.close();ClientPhasePort.install(null)
    }
    kotlin.system.exitProcess(0)
}
