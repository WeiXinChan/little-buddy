package com.littlebuddy.v2.feedback

import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.Response
import org.json.JSONObject
import java.util.Base64
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

internal interface FeedbackAttempt : AutoCloseable { fun start(listener: WebSocketListener): WebSocket }
/** This snapshot contains only the existing device credential, never an owner proof. No printable data class. */
internal class FeedbackNetworkConfig(val credential: String, val make: ()->FeedbackAttempt) {
    val binding: String = digest(credential.toByteArray(Charsets.UTF_8))
}
internal class FeedbackWireProvider(private val configuration: ()->FeedbackNetworkConfig?,
                                     private val timeoutMs: Long = 6000) : FeedbackProvider {
    private class Scope(val authority: FeedbackPageAuthority?, val generation: Long)
    private val serial=AtomicLong()
    private val caller=ThreadLocal<Scope>()
    private val active=AtomicReference<Exchange?>()
    fun <T> asPage(authority: FeedbackPageAuthority, action: ()->T): T {
        caller.set(Scope(authority,serial.get()))
        return try { action() } finally { caller.remove() }
    }
    fun cancelActive() { serial.incrementAndGet();active.getAndSet(null)?.close() }
    private fun live(scope: Scope) = scope.generation==serial.get() && (scope.authority?.current()!=false)
    override fun available(): Boolean = runCatching { configuration()!=null }.getOrDefault(false)
    override fun binding(): String? = configuration()?.binding
    override fun submit(key: String, payload: FeedbackPayload, admit: ()->Boolean): SubmitReceipt =
        throw FeedbackFailure(Failure.DENIED) // Production requires the explicit memory-admission port.
    override fun submitAdmitted(key: String, payload: FeedbackPayload, binding: String?, admit: (() -> Unit)->Boolean): SubmitReceipt {
        FeedbackKeys.checked(key,true)
        if(payload.description.isBlank() || payload.description.codePointCount(0,payload.description.length)>2000)
            throw FeedbackFailure(Failure.INVALID)
        checkedLogs(payload.logs)
        val result=request(key,"submit",binding,JSONObject().put("category",payload.category.name)
            .put("description",payload.description).put("logs",Base64.getEncoder().encodeToString(payload.logs)),admit)
        keys(result,setOf("id","submitted_at","delete_by"));id(result,key)
        val submitted=long(result,"submitted_at");val until=long(result,"delete_by")
        if(until<=submitted || until>submitted+WEEK)throw FeedbackFailure(Failure.NETWORK)
        return SubmitReceipt(submitted,until)
    }
    override fun read(key: String, binding: String?, admit: (() -> Unit)->Boolean): FeedbackRemote {
        FeedbackKeys.checked(key)
        val result=request(key,"read",binding,JSONObject(),admit)
        keys(result,setOf("id","submitted","delete_by","state","category","description","logs","reply"));id(result,key)
        val submitted=result["submitted"]?.let { long(result,"submitted") }
        val state=try { FeedbackState.valueOf(string(result,"state")) } catch(_:Exception) { throw FeedbackFailure(Failure.NETWORK) }
        if(state !in setOf(FeedbackState.SUBMITTED,FeedbackState.PROCESSING,FeedbackState.REPLIED,FeedbackState.DELETED))throw FeedbackFailure(Failure.NETWORK)
        val reply=string(result,"reply")
        if(reply.codePointCount(0,reply.length)>2000 || (state==FeedbackState.REPLIED && reply.isBlank()))throw FeedbackFailure(Failure.NETWORK)
        return FeedbackRemote(submitted,long(result,"delete_by"),state,reply)
    }
    override fun withdraw(key: String)=withdrawBound(key,null)
    override fun withdrawBound(key: String, binding: String?): DeleteReceipt {
        FeedbackKeys.checked(key)
        val result=request(key,"withdraw",binding,JSONObject(),null)
        keys(result,setOf("id","received_at","delete_by","all_copies_deleted"));id(result,key)
        val all=result["all_copies_deleted"] as? Boolean ?: throw FeedbackFailure(Failure.NETWORK)
        // Unknown legacy credential binding cannot prove deletion of another device's old copies.
        val received=long(result,"received_at");val until=long(result,"delete_by")
        if(until>received+WEEK)throw FeedbackFailure(Failure.NETWORK)
        return DeleteReceipt(received,all && binding!=null)
    }
    private fun request(key: String, operation: String, binding: String?, extra: JSONObject,
                        admit: ((()->Unit)->Boolean)?): Map<String,Any?> {
        val scope=caller.get() ?: Scope(null,serial.get())
        if(operation!="withdraw" && scope.authority==null)throw FeedbackFailure(Failure.DENIED)
        if(!live(scope))throw FeedbackFailure(Failure.DENIED)
        val config=configuration() ?: throw FeedbackFailure(Failure.UNAVAILABLE)
        if(!live(scope))throw FeedbackFailure(Failure.DENIED)
        if(binding!=null && binding!=config.binding)throw FeedbackFailure(Failure.DENIED)
        val request=UUID.randomUUID().toString()
        val body=extra.put("v",1).put("request",request).put("operation",operation).put("id",key).toString()
        if(body.toByteArray(Charsets.UTF_8).size>400000)throw FeedbackFailure(Failure.INVALID)
        val exchange=Exchange(scope,request)
        if(!active.compareAndSet(null,exchange))throw FeedbackFailure(Failure.NETWORK)
        try {
            if(!live(scope))throw FeedbackFailure(Failure.DENIED)
            val attempt=config.make();exchange.install(attempt)
            if(!live(scope) || exchange.closed())throw FeedbackFailure(Failure.DENIED)
            exchange.install(attempt.start(exchange))
            exchange.waitReady()
            // The only final decision is READY -> ADMITTED, performed under the original Grant.
            // All serialization/SSH/TLS completed first. No IO occurs inside this callback.
            if(admit!=null) {
                admit { if(scope.generation==serial.get())exchange.admit() }
            } else if(live(scope))exchange.admit() // durable original-key deletion only
            if(!exchange.admitted() || !live(scope))throw FeedbackFailure(Failure.DENIED)
            exchange.send(body)
            return exchange.waitReply()
        } finally { active.compareAndSet(exchange,null);exchange.close() }
    }
    private enum class State { CONNECTING, READY, ADMITTED, CLOSED }
    private inner class Exchange(private val scope: Scope, private val request: String): WebSocketListener(),AutoCloseable {
        private val state=AtomicReference(State.CONNECTING)
        private val socket=AtomicReference<WebSocket?>()
        private val attempt=AtomicReference<FeedbackAttempt?>()
        private val ready=CountDownLatch(1);private val done=CountDownLatch(1)
        private var result: Map<String,Any?>?=null
        private var failure: Failure?=null
        fun install(value: FeedbackAttempt) { attempt.set(value);if(closed() && attempt.compareAndSet(value,null))value.close() }
        fun install(value: WebSocket) { socket.set(value);if(closed() && socket.compareAndSet(value,null))value.cancel() }
        fun closed()=state.get()==State.CLOSED
        fun admit() { state.compareAndSet(State.READY,State.ADMITTED) }
        fun admitted()=state.get()==State.ADMITTED
        override fun onMessage(ws: WebSocket,text: String) {
            if(closed())return
            if(!live(scope)){failure=Failure.DENIED;close();return}
            try {
                val value=FeedbackJson.parse(text)
                if(state.get()==State.CONNECTING) {
                    keys(value,setOf("v","type","protocol"))
                    if(long(value,"v")!=1L || value["type"]!="feedback_ready" || value["protocol"]!="feedback-v1")throw FeedbackFailure(Failure.NETWORK)
                    if(state.compareAndSet(State.CONNECTING,State.READY))ready.countDown()
                } else if(state.get()==State.ADMITTED) {
                    if(long(value,"v")!=1L || value["request"]!=request)throw FeedbackFailure(Failure.NETWORK)
                    val ok=value["ok"] as? Boolean ?: throw FeedbackFailure(Failure.NETWORK)
                    if(ok) { keys(value,setOf("v","request","ok","result"));result=map(value["result"]) }
                    else { keys(value,setOf("v","request","ok","error"));failure=when(value["error"]) {
                        "missing","deleted","conflict","expired"->Failure.STALE;"clock"->Failure.CLOCK
                        "invalid","capacity"->Failure.INVALID;else->Failure.NETWORK } }
                    done.countDown()
                } else throw FeedbackFailure(Failure.NETWORK)
            } catch(_:Exception) { failure=Failure.NETWORK;close() }
        }
        override fun onFailure(ws:WebSocket,t:Throwable,response:Response?) { failure=Failure.NETWORK;close() }
        override fun onClosed(ws:WebSocket,code:Int,reason:String) { failure=Failure.NETWORK;close() }
        fun waitReady() { if(!ready.await(timeoutMs,TimeUnit.MILLISECONDS) || state.get()!=State.READY || failure!=null)throw FeedbackFailure(failure ?: Failure.NETWORK) }
        fun send(body:String) {
            if(!admitted() || !live(scope))throw FeedbackFailure(Failure.DENIED)
            if(socket.get()?.send(body)!=true)throw FeedbackFailure(Failure.NETWORK)
        }
        fun waitReply(): Map<String,Any?> {
            if(!done.await(timeoutMs,TimeUnit.MILLISECONDS) || closed() || !live(scope))throw FeedbackFailure(Failure.NETWORK)
            failure?.let{throw FeedbackFailure(it)}
            return result ?: throw FeedbackFailure(Failure.NETWORK)
        }
        override fun close() { state.set(State.CLOSED);result=null;runCatching{socket.getAndSet(null)?.cancel()};runCatching{attempt.getAndSet(null)?.close()};ready.countDown();done.countDown() }
    }
    companion object {
        private fun keys(value:Map<String,Any?>,expected:Set<String>) { if(value.keys!=expected)throw FeedbackFailure(Failure.NETWORK) }
        private fun string(value:Map<String,Any?>,key:String)=value[key] as? String ?: throw FeedbackFailure(Failure.NETWORK)
        private fun long(value:Map<String,Any?>,key:String):Long { val n=value[key] as? Long ?: throw FeedbackFailure(Failure.NETWORK);if(n<0 || n>Long.MAX_VALUE-WEEK)throw FeedbackFailure(Failure.NETWORK);return n }
        private fun id(value:Map<String,Any?>,key:String) { if(value["id"]!=key)throw FeedbackFailure(Failure.NETWORK) }
        @Suppress("UNCHECKED_CAST") private fun map(value:Any?)=value as? Map<String,Any?> ?: throw FeedbackFailure(Failure.NETWORK)
        private fun checkedLogs(bytes:ByteArray) {
            if(bytes.isEmpty())return
            if(bytes.size>256*1024 || bytes.any{it<0 || it==0.toByte()} || bytes.last()!=10.toByte())throw FeedbackFailure(Failure.INVALID)
            val lines=bytes.toString(Charsets.US_ASCII).dropLast(1).split('\n')
            if(lines.size>1000)throw FeedbackFailure(Failure.INVALID)
            for(line in lines) {
                val f=line.split(',');if(f.size!=6)throw FeedbackFailure(Failure.INVALID)
                try { require(f[0].toLong()>=0);LogStage.valueOf(f[1]);LogError.valueOf(f[2]);require(f[3].toInt() in 1..1_000_000)
                    require(f[4].toLong() in 0..DAY && f[5].toLong() in 0..1_000_000_000L) }
                catch(_:Exception) { throw FeedbackFailure(Failure.INVALID) }
            }
        }
    }
}
