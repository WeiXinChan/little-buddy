package com.littlebuddy.v2.feedback
import com.littlebuddy.v2.parent.*
import okhttp3.*
import java.io.File
import java.nio.file.Files
import java.net.Proxy
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import javax.crypto.KeyGenerator

fun main(args:Array<String>) {
    val mode=args[1];val url=args[0];var failure:Throwable?=null
    val root=Files.createTempDirectory("feedback-core-fixture").toFile()
    try {
        val store=object:ParentStore {var value:ParentRecord?=null;override fun read()=value
            override fun write(record:ParentRecord,authorized:()->Boolean){check(authorized());value=record} }
        val domain=ParentDomain(store,System::currentTimeMillis,{},object:OwnerProof {override fun consume(challenge:OwnerChallenge)=true},"feedback-fixture")
        val init=domain.enterPage();check(domain.replacePin("012345".toCharArray(),domain.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN,init)!!,init))
        fun authority():ParentFeedbackAuthorizer {
            val page=domain.enterPage();val grant=checkNotNull(domain.verify("012345".toCharArray(),page))
            return ParentFeedbackAuthorizer(domain,grant,FeedbackGrantGate{d,g,decision->d.acceptProtected(g,decision)})
        }
        val auth=authority();val token=AtomicReference("A".repeat(32));val opens=AtomicInteger();val closes=AtomicInteger()
        val provider=FeedbackWireProvider({
            val current=token.get()
            FeedbackNetworkConfig(current) {
                opens.incrementAndGet()
                val http=OkHttpClient.Builder().proxy(Proxy.NO_PROXY).retryOnConnectionFailure(false)
                    .followRedirects(false).followSslRedirects(false).build()
                object:FeedbackAttempt {
                    override fun start(listener:WebSocketListener)=http.newWebSocket(Request.Builder().url(url)
                        .header("Authorization","Bearer $current").build(),listener)
                    override fun close(){closes.incrementAndGet();http.dispatcher.cancelAll();http.connectionPool.evictAll();http.dispatcher.executorService.shutdown()}
                }
            }
        },1500)
        val key=KeyGenerator.getInstance("AES").apply{init(256)}.generateKey()
        val files=PrivateVaultFiles(root)
        val traced=object:FeedbackProvider by provider {
            override fun submitAdmitted(id:String,payload:FeedbackPayload,binding:String?,admit:(()->Unit)->Boolean):SubmitReceipt =
                try {provider.submitAdmitted(id,payload,binding,admit)} catch(e:FeedbackFailure) {println("fixture_submit_failure_reason="+e.reason);throw e}
        }
        val core=FeedbackCore(FeedbackVault(files,key),System::currentTimeMillis,auth,traced)
        if(mode=="logs")core.record(mapOf("stage" to LogStage.CONNECT,"error" to LogError.NONE,"version" to 18,"elapsedMs" to 0L,"usage" to 0L))
        val id=provider.asPage(auth) {
            core.startDraft(Category.IMAGE,"synthetic parent fixture")
            if(mode=="logs")core.selectLogs(System.currentTimeMillis()-10000,System.currentTimeMillis())
            val confirmation=core.preview()
            if(mode=="revoke")Thread {Thread.sleep(100);auth.close();domain.revoke();provider.cancelActive()}.start()
            core.submit(confirmation)
        }
        val uuid=FeedbackKeys.checked(id,true)
        check(uuid.mostSignificantBits ushr 16>0)
        if(mode=="revoke") {
            val fresh=authority();val reopened=FeedbackCore(FeedbackVault(files,key),System::currentTimeMillis,fresh,provider)
            check(reopened.list().single().id==id && reopened.list().single().state==FeedbackState.SEND_FAILED)
        } else {
            val initial=core.list().single();check(initial.id==id)
            val reopened=FeedbackCore(FeedbackVault(files,key),System::currentTimeMillis,auth,provider)
            check(reopened.list().single().id==id)
            if(mode in setOf("timeout","binding"))check(initial.state==FeedbackState.SEND_FAILED)
            else check(initial.state==FeedbackState.SUBMITTED)
            if(mode=="binding")token.set("B".repeat(32))
            else if(mode !in setOf("timeout")) {
                if(mode=="reply-revoke")Thread {Thread.sleep(100);auth.invalidate();provider.cancelActive()}.start()
                val before=core.list().single().deleteBy
                if(mode=="reply-revoke") {
                    try {provider.asPage(auth){core.refresh(id)};error("late read returned") }catch(_:FeedbackFailure){}
                    check(core.list().single().reply.isNullOrEmpty());check(core.list().single().deleteBy==before)
                } else {
                    provider.asPage(auth){core.refresh(id)}
                    val reply=core.list().single();check(reply.state==FeedbackState.REPLIED && reply.reply=="synthetic reply")
                    check(reply.deleteBy==before)
                }
            }
            provider.asPage(auth){core.withdraw(id);core.drainDeletions()}
            val end=core.list().single()
            check(end.id==id && end.description==null && end.reply==null)
            check(end.state==when(mode){"false"->FeedbackState.DELETING;"binding"->FeedbackState.DELETE_FAILED;else->FeedbackState.DELETED})
        }
        check(opens.get()==closes.get()){"attempt leaked"}
        provider.cancelActive()
        println("FEEDBACK_TLS $mode PASS; original_uuid7=1 final_grant=1 no_upload_replay=1; synthetic only")
    } catch(t:Throwable){failure=t}
    finally {root.deleteRecursively()}
    failure?.let{it.printStackTrace();kotlin.system.exitProcess(1)}
    kotlin.system.exitProcess(0)
}
