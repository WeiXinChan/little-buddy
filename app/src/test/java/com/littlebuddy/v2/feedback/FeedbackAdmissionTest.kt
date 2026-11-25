package com.littlebuddy.v2.feedback
import com.littlebuddy.v2.parent.*
import okhttp3.*
import okio.ByteString
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files
import javax.crypto.KeyGenerator
import java.util.concurrent.*
import java.util.concurrent.atomic.*

class FeedbackAdmissionTest {
    @Test fun finalGrantDecisionDoesNotUseBusyEarlyCheckOrHoldGrantAcrossTransport() {
        val store=object:ParentStore {var r:ParentRecord?=null;override fun read()=r
            override fun write(record:ParentRecord,authorized:()->Boolean){check(authorized());r=record} }
        val domain=ParentDomain(store,System::currentTimeMillis,{},object:OwnerProof {override fun consume(challenge:OwnerChallenge)=true},"admission-test")
        val first=domain.enterPage();check(domain.replacePin("012345".toCharArray(),domain.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN,first)!!,first))
        val page=domain.enterPage();val grant=domain.verify("012345".toCharArray(),page)!!
        val auth=ParentFeedbackAuthorizer(domain,grant,FeedbackGrantGate{d,g,a->d.acceptProtected(g,a)})
        var sent=0
        val provider=FeedbackWireProvider({FeedbackNetworkConfig("A".repeat(32)) {
            object:FeedbackAttempt {
                override fun start(listener:WebSocketListener):WebSocket {
                    assertNotNull(domain.volumeLimit(grant)) // No grant lock during connect/IO.
                    val socket=object:WebSocket {
                        override fun request()=Request.Builder().url("https://127.0.0.1:19483/v2/feedback").build()
                        override fun queueSize()=0L
                        override fun send(text:String):Boolean {
                            assertNotNull(domain.volumeLimit(grant));sent++
                            val q=JSONObject(text);val at=System.currentTimeMillis()
                            listener.onMessage(this,JSONObject().put("v",1).put("request",q.getString("request")).put("ok",true)
                                .put("result",JSONObject().put("id",q.getString("id")).put("submitted_at",at).put("delete_by",at+WEEK)).toString())
                            return true
                        }
                        override fun send(bytes:ByteString)=false
                        override fun close(code:Int,reason:String?)=true
                        override fun cancel(){}
                    }
                    listener.onMessage(socket,"{\"v\":1,\"type\":\"feedback_ready\",\"protocol\":\"feedback-v1\"}")
                    return socket
                }
                override fun close(){}
            }
        }})
        val root=Files.createTempDirectory("feedback-admit-").toFile()
        try {
            val key=KeyGenerator.getInstance("AES").apply{init(256)}.generateKey()
            val core=FeedbackCore(FeedbackVault(PrivateVaultFiles(root),key),System::currentTimeMillis,auth,provider)
            provider.asPage(auth){core.startDraft(Category.OTHER,"synthetic");core.submit(core.preview())}
            assertEquals(1,sent);assertEquals(FeedbackState.SUBMITTED,core.list().single().state)
        }finally{root.deleteRecursively()}
    }
    @Test fun cancellationBeforeAttemptInstallClosesExactlyOnceAndNeverStarts() {
        val entered=CountDownLatch(1);val release=CountDownLatch(1);val closed=AtomicInteger();val started=AtomicInteger()
        val auth=object:FeedbackPageAuthority {override fun current()=true;override fun close(){};override fun invalidate(){}
            override fun prepare(operation:Operation,digest:String):ParentIntent?=null
            override fun accept(intent:ParentIntent,operation:Operation,digest:String,acceptance:()->Unit)=false }
        val provider=FeedbackWireProvider({FeedbackNetworkConfig("A".repeat(32)) {
            entered.countDown();check(release.await(2,TimeUnit.SECONDS))
            object:FeedbackAttempt {override fun start(listener:WebSocketListener):WebSocket {started.incrementAndGet();error("late start")}
                override fun close(){closed.incrementAndGet()} }
        }})
        val error=AtomicReference<Throwable?>();val thread=Thread {
            try {provider.asPage(auth){provider.submitAdmitted(FeedbackKeys.create(System.currentTimeMillis()),FeedbackPayload(Category.OTHER,"synthetic",byteArrayOf()),provider.binding()){a->a();true}}}
            catch(t:Throwable){error.set(t)}
        };thread.start();assertTrue(entered.await(1,TimeUnit.SECONDS));provider.cancelActive();release.countDown();thread.join(2000)
        assertFalse(thread.isAlive);assertEquals(0,started.get());assertEquals(1,closed.get());assertEquals(Failure.DENIED,(error.get() as FeedbackFailure).reason)
    }
}
