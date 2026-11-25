package com.littlebuddy.v2.feedback

import android.content.Context
import com.littlebuddy.v2.parent.ParentDomain
import com.littlebuddy.v2.transport.Target
import com.littlebuddy.v2.transport.V2Ssh
import com.littlebuddy.v2.transport.V2SshProfile
import okhttp3.ConnectionPool
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.net.Proxy
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/** Only the already-issued private device connection. No URL/token input or public route fallback. */
internal class AndroidFeedbackTransport(context: Context) {
    private val app=context.applicationContext
    private val domain=AtomicReference<ParentDomain?>()
    fun configure(value: ParentDomain) { domain.set(value) }
    fun configuration(): FeedbackNetworkConfig? {
        val source=domain.get() ?: com.littlebuddy.v2.parent.AndroidParentRuntime.existing(app)?.also { domain.compareAndSet(null,it) }
        val connection=source?.childConfiguration()?.connection ?: return null
        if(connection.sshUser==null || connection.address!="wss://127.0.0.1:19483/v2/voice")return null
        connection.requireRunnable()
        return FeedbackNetworkConfig(connection.credential) {
            val ssh=V2Ssh(V2SshProfile.load(app,connection.sshUser))
            try {
                val base=OkHttpClient.Builder().proxy(Proxy.NO_PROXY).cache(null).connectionPool(ConnectionPool())
                    .followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false)
                    .connectTimeout(5,TimeUnit.SECONDS).readTimeout(5,TimeUnit.SECONDS).build()
                val http=ssh.client(base,Target.FEEDBACK)
                val request=Request.Builder().url("wss://127.0.0.1:19483/v2/feedback")
                    .header("Authorization","Bearer ${connection.credential}")
                    .header("Cache-Control","no-store").build()
                object:FeedbackAttempt {
                    override fun start(listener:WebSocketListener):WebSocket=http.newWebSocket(request,listener)
                    override fun close() {
                        runCatching { ssh.close() };runCatching { http.dispatcher.cancelAll() }
                        runCatching { http.connectionPool.evictAll() };http.dispatcher.executorService.shutdown()
                    }
                }
            } catch(f:Exception) { ssh.close();throw f }
        }
    }
}
