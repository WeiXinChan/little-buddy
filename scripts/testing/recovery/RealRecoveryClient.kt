package com.littlebuddy.v2
import android.os.Handler
import android.os.SystemClock
import android.media.AudioRecord
import android.media.AudioTrack
import android.content.res.AssetManager
import com.littlebuddy.SherpaWake
import com.littlebuddy.v2.parent.PinDiagnostic
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Production Capture + actual VoiceClient/TLS/Playback, controlled continuous native/KWS ports. */
fun main(args:Array<String>){
    Thread.setDefaultUncaughtExceptionHandler{_,t->t.printStackTrace();System.err.println("RECOVERY_UNCAUGHT "+t.javaClass.simpleName);kotlin.system.exitProcess(1)}
    val owner=Handler();val done=CountDownLatch(1);val slot=OutputSlot();val episode=RecoveryEpisode()
    var cap:Capture?=null;var firstFailure=0;var secondFailure=0;var connects=0;var heads=0;var replies=0;var imported=0
    var trusted:ServerFailure?=null;var eligibility=false
    var callbackStage="NONE";var callbackException=false;var oldReleased=false
    var wakeBoot=-1L;var rejectedBoot=-1L;var readyCount=0;var unexpectedCapture=false
    val trace=java.util.concurrent.CopyOnWriteArrayList<String>()
    val physical=PinDiagnostic.Scope(1,1,2);var binds=0;var captureStarts=0
    val mode=args[1]
    val denied=mode in setOf("stale_scope","quota","auth","timeout_idle","timeout_stale","safety","unknown","unscoped")
    val expected=when(mode){"stale_scope","timeout_idle","timeout_stale","unscoped"->null;"quota"->ServerFailure.QUOTA;"auth"->ServerFailure.AUTH;"timeout","timeout_slow"->ServerFailure.TIMEOUT;"safety"->ServerFailure.SAFETY;"unknown"->ServerFailure.UNKNOWN;else->ServerFailure.VOICE}
    val failures=java.util.concurrent.CopyOnWriteArrayList<PinDiagnostic.FailSource>()
    PinDiagnostic.installRuntime{
        if(it.stage==PinDiagnostic.RuntimeStage.CLIENT_FAIL){eligibility=it.recoveryEligible;failures+=it.source;trace+="FAIL_${it.source.name}_${it.scope.transport}"}
        if(it.stage==PinDiagnostic.RuntimeStage.CAPTURE_START)captureStarts++
        if(it.stage==PinDiagnostic.RuntimeStage.RECOVERY_BIND){
            check(it.scope==physical && it.currentTransport==2L && it.currentCapture==2L);binds++
        }
    }
    var secondCreated=false;lateinit var second:VoiceClient
    var handoff:RecoveryHandoff?=null
    fun recorder(port:CaptureSessionPort,scope:PinDiagnostic.Scope=PinDiagnostic.Scope(1,0,1)):Capture {
        AudioRecord.reset(10000);AudioRecord.continuous=true;SystemClock.realtime=true;SherpaWake.detectAfter=3
        return Capture(AssetManager(),owner,port,{true},modelDirectory=null,diagnosticScope=scope,failed={unexpectedCapture=true;trace+="CAPTURE_GUARD";done.countDown()}).also{cap=it;it.start()}
    }
    lateinit var first:VoiceClient
    first=VoiceClient(owner,{},{},{_,_->},failed={
        firstFailure++;trace+="OLD_CALLBACK"
        try {
        callbackStage="TYPED"
        check(trusted==expected){"mode=$mode trusted=$trusted sources=$failures"}
        callbackStage="OLD_RELEASE"
        cap!!.close();check(cap!!.nativeProof.released && ProcessRecorders.released());check(slot.idle);oldReleased=true;trace+="OLD_RELEASED"
        if(denied){check(!eligibility);done.countDown();return@VoiceClient}
        check(eligibility && trusted?.wakeRecoveryCandidate==true)
        callbackStage="EPISODE"
        check(episode.begin());val ticket=episode.grant(true,true)!!
        handoff=RecoveryHandoff(SystemClock::elapsedRealtime,{owner.post(it)},{episode.current(ticket)},
            connect={b->
                check(episode.consumeWake(ticket));connects++;wakeBoot=b.boot;trace+="NEW_WAKE_CONNECT"
                second=VoiceClient(owner,{},{},{_,_->},failed={secondFailure++;trace+="NEW_CLIENT_FAIL";cap!!.close();done.countDown()},
                    requiredContract=ReleaseCompatibility.CONTRACT,outputSlot=slot,captureImport=true,permitted={handoff!!.admitted()},diagnosticScope=PinDiagnostic.Scope(1,2,0),
                    ready={readyCount++;trace+="READY";check(handoff!!.ready(second));PinDiagnostic.runtime(checkNotNull(episode.binding(ticket,physical,2,b))) },completed={_,_->replies++;owner.postDelayed({done.countDown()},20)})
                secondCreated=true;second.connect(args[0],"A".repeat(32))
            },cancelCue={},failed={secondFailure++;rejectedBoot=handoff!!.rejectedAtBoot;trace+="HANDOFF_REJECT";cap!!.close();done.countDown()},imported={
                imported++;check(episode.succeeded(ticket)!=null)
                // Native source keeps running; the controlled VAD naturally reaches silence.
                second.quiet()
            })
        callbackStage="NEW_CAPTURE"
        recorder(handoff!!,physical)
        callbackStage="RETURNED"
        } catch(_:Throwable){callbackException=true;trace+="CALLBACK_GUARD_$callbackStage";done.countDown()}
    },requiredContract=ReleaseCompatibility.CONTRACT,outputSlot=slot,failureClassified={trusted=it},diagnosticScope=PinDiagnostic.Scope(1,0,0),
        ready={recorder(ClientCapturePort(first))})
    ClientPhasePort.install{
        if(secondCreated && it.phase in setOf(ClientPhase.PROBE_SENT,ClientPhase.SEAL_SENT))check(imported==1 && handoff?.state==RecoveryHandoff.State.LIVE){"gate tick before FIFO import"}
        if(it.phase==ClientPhase.FIRST_NATIVE_HEAD_PROGRESS)heads++
    }
    owner.post{first.connect(args[0],"A".repeat(32))}
    try{
        check(done.await(9,TimeUnit.SECONDS)){"recovery wire incomplete first=$firstFailure connects=$connects import=$imported state=${handoff?.state} second=$secondFailure heads=$heads replies=$replies failures=$failures"}
        val barrier=CountDownLatch(1);owner.post{barrier.countDown()};check(barrier.await(1,TimeUnit.SECONDS))
        println("RECOVERY_TRACE mode=$mode first_callbacks=$firstFailure trusted=$trusted old_released=$oldReleased callback_stage=$callbackStage callback_exception=$callbackException capture_guard=$unexpectedCapture ready=$readyCount wake_boot=$wakeBoot reject_boot=$rejectedBoot reason=${handoff?.rejection} sources=$failures steps=$trace")
        check(!callbackException && !unexpectedCapture)
        check(firstFailure==1)
    if(mode !in setOf("slow","timeout_slow"))check(failures.size==1)
    check(failures.first()==if(mode=="unscoped")PinDiagnostic.FailSource.RECEIVE_PROTOCOL else PinDiagnostic.failSource((if(mode.startsWith("timeout"))ServerFailure.TIMEOUT else expected ?: ServerFailure.VOICE).localCode))
        if(denied){check(connects==0 && heads==0 && binds==0)}
        else if(mode in setOf("slow","timeout_slow")){check(secondFailure>=1 && heads==0 && imported==0 && oldReleased && connects==1 && readyCount==0 && rejectedBoot>=wakeBoot+2500 && handoff!!.rejection==RecoveryHandoff.Rejection.CONNECT_DEADLINE);check(handoff!!.retainedSamples()==0 && handoff!!.state==RecoveryHandoff.State.CANCELLED)}
        else{check(connects==1 && secondFailure==0 && imported==1 && heads==1 && replies==1 && binds==1 && captureStarts==2)}
        println("RECOVERY_TLS mode=$mode first_failure=$firstFailure connections=$connects import=$imported heads=$heads replies=$replies second_failure=$secondFailure")
    }finally{
        val closed=CountDownLatch(1);owner.post{cap?.close();first.close();if(secondCreated)second.close();closed.countDown()};check(closed.await(2,TimeUnit.SECONDS));owner.close()
        check(ProcessRecorders.released());check(AudioTrack.instances.all{it.state==0});PinDiagnostic.installRuntime(null);ClientPhasePort.install(null)
    }
    kotlin.system.exitProcess(0)
}
