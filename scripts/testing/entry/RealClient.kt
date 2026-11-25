package com.littlebuddy.v2

import android.os.Handler
import com.littlebuddy.v2.parent.*
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Actual VoiceClient on authenticated TLS, with only Android owner/JSON ports adapted for JVM.
 * No receive injection, no media/OS object or cloud speech/model is created. */
private fun runClient(args: Array<String>) {
    val owner=Handler(); val finished=CountDownLatch(1); var failure: Throwable?=null
    lateinit var client: VoiceClient
    var ready=0; var entry=0; var paused=0; var waiting=0; var pages=0; var grants=0
    val late=args.getOrNull(1)=="late"
    val store=object: ParentStore {
        var value: ParentRecord?=null
        override fun read()=value
        override fun write(record: ParentRecord,authorized: ()->Boolean) { check(authorized()); value=record }
    }
    val domain=ParentDomain(store,{System.nanoTime()/1_000_000},{},object:OwnerProof {
        override fun consume(challenge: OwnerChallenge)=true
    },"entry-test-only")
    val page=domain.enterPage();check(domain.replacePin("012345".toCharArray(),
        domain.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN,page)!!,page))
    val model=ParentPanelModel({domain},{it()},{it()},{state ->
        pages++; if (state.mode==PanelMode.SETTINGS) grants++
    },{ check(client.resumeManagement(ParentPlaybackSettings(),null)) })
    client=VoiceClient(owner,{}, {}, {_,_->error("unexpected reveal")},
        failed={failure=AssertionError("client failed before waiting_wake");finished.countDown()},
        management={token ->
            entry++
            if (late) {
                client.frame(ShortArray(320),true);client.quiet()
                check(!client.acceptManagementEntry(token) { error("stale entry borrowed current scope") })
                finished.countDown()
                return@VoiceClient
            }
            check(client.acceptManagementEntry(token) { true /* current memory admission; never grants PIN rights */ })
            check(client.stopForManagement());check(client.pauseManagement())
        },managed={phase ->
            when(phase) {
                ManagementState.Phase.PAUSED -> {
                    paused++;model.open();check(model.state.mode==PanelMode.VERIFY);check(grants==0)
                    model.exit() // Current cancellation, with no PIN verification and no Grant.
                }
                ManagementState.Phase.WAITING_WAKE -> {
                    waiting++;check(!client.isAwake);finished.countDown()
                }
                ManagementState.Phase.DEAD -> { failure=AssertionError("management died");finished.countDown() }
                else -> Unit
            }
        },requiredContract=ReleaseCompatibility.CONTRACT,
        ready={
            ready++;client.wake()
            client.frame(ShortArray(320),true);client.quiet()
        })
    owner.post { try { client.connect(args[0],"A".repeat(32)) } catch(t:Throwable) { failure=t;finished.countDown() } }
    try {
        check(finished.await(12,TimeUnit.SECONDS)) { "natural management entry did not reach waiting_wake" }
        failure?.let { throw it }
        if (late) {
            check(ready==1 && entry==1 && paused==0 && waiting==0 && pages==0 && grants==0)
            println("REAL_CLIENT late_entry_rejected=1 pages=0 grants=0; JVM ports, no device")
        } else {
            check(ready==1 && entry==1 && paused==1 && waiting==1 && pages>0 && grants==0)
            println("REAL_CLIENT ready=1 natural_entry=1 paused=1 verify_page=1 grants=0 cancelled=1 waiting_wake=1; JVM ports, no device")
        }
    } finally { owner.post {client.close()};Thread.sleep(50);owner.close() }
}

fun main(args: Array<String>) {
    try { runClient(args); kotlin.system.exitProcess(0) }
    catch (failure: Throwable) { failure.printStackTrace(); kotlin.system.exitProcess(1) }
}
