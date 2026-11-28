package com.littlebuddy.v2

import android.os.Handler
import android.os.SystemClock
import android.media.AudioTrack
import com.littlebuddy.v2.parent.PinDiagnostic
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Real VoiceClient/Playback, controlled BOOT clock and native ports. No receive injection. */
fun main(args:Array<String>) {
    Thread.setDefaultUncaughtExceptionHandler{_,_->System.err.println("UNKNOWN_FIXTURE_UNCAUGHT");kotlin.system.exitProcess(1)}
    val mode=args[1];val owner=Handler();val done=CountDownLatch(1)
    val failures=java.util.concurrent.CopyOnWriteArrayList<PinDiagnostic.RuntimeEvent>()
    var localBegin=0;var localHead=0;var localEnd=0;var localCancel=0;var allowed=true;var localTrack:AudioTrack?=null;var failed=0;var clarified=0;var serialAtTerminal=-1L;var phaseUnknown=0;var ordinaryComplete=false;var firstRequest=false;var waiting=false;var tested=false;var secondHead=false
    lateinit var client:VoiceClient
    val expectedFault=mode in setOf("stale_epoch","stale_revision","stale_new_input","expired","provider","release_failure","local_release_failure","asset_late")
    fun newSpeech(){client.frame(ShortArray(320),true,SystemClock.elapsedRealtime());client.quiet();SystemClock.advance(301)}
    fun afterWireBarrier(){
        if(tested)return;tested=true;waiting=false
        if(mode in setOf("incomplete","thinking")){
            SystemClock.advance(1200);owner.postDelayed({done.countDown()},50);return
        }
        SystemClock.advance(15001)
        owner.postDelayed({
            if(failed>0){done.countDown();return@postDelayed}
            if(expectedFault){done.countDown();return@postDelayed}
            val old=AudioTrack.instances.first()
            check(old.plays==if(mode=="noise")2 else 1){"old audio replayed"}
            if(mode in setOf("unknown","empty","unknown_complete","local_duplicate","stop"))check(old.state==AudioTrack.STATE_UNINITIALIZED)
            newSpeech()
        },50)
    }
    PinDiagnostic.installRuntime{if(it.stage==PinDiagnostic.RuntimeStage.CLIENT_FAIL)failures.add(it)}
    ClientPhasePort.install{e->
        when(e.phase){
            ClientPhase.LOCAL_CLARIFY_BEGIN->{localBegin++;localTrack=AudioTrack.instances.last()}
            ClientPhase.LOCAL_CLARIFY_HEAD->{localHead++
                when(mode){
                    "local_input"->{newSpeech()}
                    "local_candidate"->{client.candidate();owner.postDelayed({done.countDown()},60)}
                    "local_management"->{check(client.stopForManagement());owner.postDelayed({done.countDown()},60)}
                    "local_close"->{client.close();owner.postDelayed({done.countDown()},60)}
                    "local_background"->{allowed=false}
                    "local_release_failure"->{AudioTrack.releaseFails=true}
                }
            }
            ClientPhase.LOCAL_CLARIFY_END->{localEnd++;if(mode in setOf("unknown","empty","unknown_complete","local_duplicate"))afterWireBarrier()}
            ClientPhase.LOCAL_CLARIFY_CANCEL->{localCancel++}
            else->Unit
        }
        if(e.phase.name=="INPUT_UNRECOGNIZED"){phaseUnknown++;serialAtTerminal=client.inputSerial}
        if(e.phase==ClientPhase.PROBE_SENT && e.revision==1L){
            waiting=true
            when(mode){
                "stale_new_input"->newSpeech()
                "expired"->SystemClock.advance(15001)
                "management"->{check(client.stopForManagement());SystemClock.advance(15001);owner.postDelayed({done.countDown()},80)}
                "cancel"->{client.close();SystemClock.advance(15001);owner.postDelayed({done.countDown()},80)}
                "release_failure"->AudioTrack.releaseFails=true
            }
        }
        if(e.phase==ClientPhase.ENDPOINT_RECEIVED && e.accepted && (e.revision>=2 || mode in setOf("unknown_complete","late_bound")))SystemClock.advance(1100)
        if(e.phase==ClientPhase.FIRST_NATIVE_HEAD_PROGRESS && e.stream>=2){secondHead=true;owner.postDelayed({done.countDown()},80)}
    }
    client=VoiceClient(owner,{s->
        if(s=="clarify")clarified++
        if(waiting && mode !in setOf("unknown","empty","unknown_complete","local_duplicate","local_input","local_candidate","local_management","local_close","local_background","local_release_failure","asset_late") && s in setOf("listening","waiting_incomplete","waiting_thinking","waiting_complete") && mode !in setOf("unknown_complete","late_bound"))afterWireBarrier()

    },{},{_,_->},failed={failed++;done.countDown()},requiredContract=ReleaseCompatibility.CONTRACT,
        diagnosticScope=PinDiagnostic.Scope(10,20,0),permitted={allowed},
        clarification={if(mode=="asset_late")SystemClock.advance(15001);ShortArray(48000){(it%31).toShort()}},
        ready={client.wake();SystemClock.advance(600)},
        completed={_,_->if(!firstRequest){firstRequest=true;newSpeech()}else{ordinaryComplete=true}})
    owner.post{client.connect(args[0],"A".repeat(32))}
    try{
        check(done.await(5,TimeUnit.SECONDS)){"bounded wire barrier missing"}
        val pump=failures.firstOrNull()?.pump?.name ?: "NONE"
        println("LOCAL_OBS begin=$localBegin head=$localHead end=$localEnd cancel=$localCancel tracks=${AudioTrack.instances.size}")
        println("UNKNOWN_OBS mode=$mode failed=$failed pump=$pump clarify=$clarified terminal=$phaseUnknown second_head=$secondHead old_plays=${AudioTrack.instances.firstOrNull()?.plays} released=${AudioTrack.instances.firstOrNull()?.state==0}")
        when {
            mode=="local_background"->{check(failed==1 && localHead==1 && localEnd==0);check(AudioTrack.instances.all{it.state==0})}
            mode in setOf("local_candidate","local_management","local_close")->{check(failed==0 && localHead==1 && localEnd==0 && localCancel==if(mode=="local_candidate")1 else 0);check(localTrack?.state==0)}
            mode=="local_release_failure"->{check(failed==1 && localEnd==0 && client.quarantined)}
            mode=="asset_late"->{check(failed==1 && localBegin==0 && localHead==0)}
            expectedFault->{
                check(failed==1 && phaseUnknown==0)
                val expected=when(mode){"provider"->PinDiagnostic.FailSource.SERVER_VOICE;"release_failure"->PinDiagnostic.FailSource.RELEASE;else->null}
                if(expected!=null)check(failures.single().source==expected)
                else check(failures.single().pump==PinDiagnostic.PumpStep.INPUT_RESPONSE_DEADLINE || mode=="expired")
                if(mode=="release_failure"){check(client.quarantined);check(client.inputSerial==0L)} else check(AudioTrack.instances.all{it.state==0})
            }
            mode in setOf("incomplete","thinking","management","cancel")->{check(failed==0 && clarified==0 && phaseUnknown==0 && !secondHead)}
            else->{
                check(failed==0){"unrecognized wait reached the original15s failure"}
                check(secondHead && ordinaryComplete){"natural next speech did not complete real Playback head/reply_end"}
                if(mode in setOf("unknown","empty","unknown_complete","local_duplicate")){check(phaseUnknown==1 && clarified==1);check(localBegin==1 && localHead==1 && localEnd==1 && localCancel==0);check(localTrack?.state==0);check(serialAtTerminal==if(mode=="unknown_complete")2L else 1L)}
                else if(mode=="local_input")check(localHead==1 && localEnd==0 && localCancel==1) else check(phaseUnknown==0)
            }
        }
    }finally{
        AudioTrack.releaseFails=false
        val closed=CountDownLatch(1);owner.post{client.close();closed.countDown()};check(closed.await(1,TimeUnit.SECONDS))
        owner.close();ClientPhasePort.install(null);PinDiagnostic.installRuntime(null)
    }
    kotlin.system.exitProcess(0)
}
