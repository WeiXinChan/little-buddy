package com.littlebuddy.v2

import android.os.Handler
import com.littlebuddy.v2.parent.PinDiagnostic
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Actual production client; no receive injection, provider, recorder or model. */
private fun runExpiry(args:Array<String>) {
    val owner=Handler();val done=CountDownLatch(1)
    val errors=java.util.concurrent.CopyOnWriteArrayList<Throwable>()
    val diagnostics=java.util.concurrent.CopyOnWriteArrayList<PinDiagnostic.RuntimeEvent>()
    var ended=0;var failed=0;var barriers=0
    val mode=args[1];lateinit var client:VoiceClient
    fun finish(){owner.postDelayed({done.countDown()},150)}
    PinDiagnostic.installRuntime{diagnostics.add(it)}
    client=VoiceClient(owner,{status->if(status=="listening")barriers++},{},{_,_->error("no images")},
        failed={failed++;finish()},sessionEnded={ended++;finish()},
        requiredContract=ReleaseCompatibility.CONTRACT,
        ready={if(mode=="management")check(client.stopForManagement())})
    owner.post{try{client.connect(args[0],"A".repeat(32))}catch(t:Throwable){errors.add(t);done.countDown()}}
    try {
        check(done.await(6,TimeUnit.SECONDS)){"bounded fixture completion missing"}
        check(errors.isEmpty())
        if(mode=="timeout" || mode=="management") {
            check(ended==0 && failed==1){"terminal/failure counts differ"}
            val expected=if(mode=="timeout")PinDiagnostic.FailSource.SERVER_TIMEOUT else PinDiagnostic.FailSource.MANAGEMENT
            check(diagnostics.any{it.stage==PinDiagnostic.RuntimeStage.CLIENT_FAIL && it.source==expected})
            if(mode=="timeout")check(diagnostics.any{it.source==expected && it.wire==PinDiagnostic.WireKind.FAILURE && it.point==PinDiagnostic.WirePoint.DISPATCH})
        } else {
            check(ended==1 && failed==0){"close/onClosed/duplicate changed terminal outcome"}
            if(mode=="stale")check(barriers==1){"stale frames ended before wire barrier"}
        }
        println("REAL_EXPIRY mode=$mode ended=$ended failed=$failed barriers=$barriers")
    } finally {
        val closed=CountDownLatch(1);owner.post{client.close();closed.countDown()}
        check(closed.await(1,TimeUnit.SECONDS));owner.close();PinDiagnostic.installRuntime(null)
    }
}

fun main(args:Array<String>) {
    try {runExpiry(args);kotlin.system.exitProcess(0)}
    catch(t:Throwable){t.printStackTrace();kotlin.system.exitProcess(1)}
}
