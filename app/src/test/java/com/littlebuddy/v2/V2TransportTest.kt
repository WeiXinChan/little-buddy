package com.littlebuddy.v2

import com.littlebuddy.v2.parent.*
import com.littlebuddy.v2.transport.*
import okhttp3.OkHttpClient
import okhttp3.Request
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.io.IOException
import java.net.Proxy
import java.util.Properties

class V2TransportTest {
    @Test fun realLoopbackUsesMappedSocketThroughOkHttp() {
        val server=java.net.ServerSocket(0,1,java.net.InetAddress.getByName("127.0.0.1"))
        server.soTimeout=2000
        val failure=java.util.concurrent.atomic.AtomicReference<Throwable?>()
        val thread=Thread {
            try { server.accept().use { socket ->
                socket.soTimeout=2000
                val input=socket.getInputStream().bufferedReader()
                while (!input.readLine().isNullOrEmpty()) { }
                socket.getOutputStream().write("HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK".toByteArray())
            } } catch(e:Throwable) { failure.set(e) }
        }
        thread.start()
        val factory=object:javax.net.SocketFactory() {
            override fun createSocket()=V2MappedSocket { server.localPort }
            override fun createSocket(h:String,p:Int):java.net.Socket=error("unsupported")
            override fun createSocket(h:String,p:Int,l:java.net.InetAddress,lp:Int):java.net.Socket=error("unsupported")
            override fun createSocket(h:java.net.InetAddress,p:Int):java.net.Socket=error("unsupported")
            override fun createSocket(h:java.net.InetAddress,p:Int,l:java.net.InetAddress,lp:Int):java.net.Socket=error("unsupported")
        }
        val client=OkHttpClient.Builder().proxy(Proxy.NO_PROXY).retryOnConnectionFailure(false).socketFactory(factory).build()
        try {
            client.newCall(Request.Builder().url("http://127.0.0.1:19483/v2/voice").build()).execute().use {
                assertEquals(200,it.code);assertEquals("OK",it.body!!.string())
            }
        } finally { server.close();thread.join(3000);client.connectionPool.evictAll();client.dispatcher.executorService.shutdownNow() }
        assertFalse(thread.isAlive);failure.get()?.let { throw AssertionError(it) }
    }
    @Test fun mappedSocketRejectsUnresolvedWrongPortAndClosedOwner() {
        for (target in listOf(java.net.InetSocketAddress.createUnresolved("127.0.0.1",19483),java.net.InetSocketAddress("127.0.0.1",19443),java.net.InetSocketAddress("127.0.0.2",19483))) {
            V2MappedSocket { 12345 }.use { socket ->
                try { socket.connect(target,100);fail("unsafe mapping") } catch(_:IOException) { }
                assertFalse(socket.isConnected)
            }
        }
        V2MappedSocket { error("closed") }.use { socket ->
            try { socket.connect(java.net.InetSocketAddress("127.0.0.1",19483),100);fail("closed owner") } catch(_:IllegalStateException) { }
        }
    }
    @Test fun diagnosticNeverEmitsExceptionText() {
        val seen=mutableListOf<Pair<PinDiagnostic.Stage,PinDiagnostic.Reason>>()
        PinDiagnostic.install { _,_,s,r -> seen.add(s to r) }
        try {
            PinDiagnostic.runtimeError(PinDiagnostic.Stage.WSS,java.net.SocketException("SECRET raw packet").apply {
                initCause(javax.net.ssl.SSLHandshakeException("SECRET token"))
            })
            assertTrue(seen.contains(PinDiagnostic.Stage.ERROR_CHAIN to PinDiagnostic.Reason.SOCKET_ERROR))
            assertTrue(seen.contains(PinDiagnostic.Stage.ERROR_CHAIN to PinDiagnostic.Reason.TLS_HANDSHAKE))
            assertTrue(seen.contains(PinDiagnostic.Stage.WSS to PinDiagnostic.Reason.SOCKET_ERROR))
            assertFalse(seen.toString().contains("SECRET"))
        } finally { PinDiagnostic.install(null) }
    }
    @Test fun realTlsWebSocketUpgradeThroughMappedSocket() {
        val keys=java.security.KeyStore.getInstance("PKCS12").apply {
            File(System.getProperty("loopback.p12")).inputStream().use { load(it,"fixture".toCharArray()) }
        }
        val km=javax.net.ssl.KeyManagerFactory.getInstance(javax.net.ssl.KeyManagerFactory.getDefaultAlgorithm()).apply { init(keys,"fixture".toCharArray()) }
        val tm=javax.net.ssl.TrustManagerFactory.getInstance(javax.net.ssl.TrustManagerFactory.getDefaultAlgorithm()).apply { init(keys) }
        val trust=tm.trustManagers.filterIsInstance<javax.net.ssl.X509TrustManager>().single()
        val tls=javax.net.ssl.SSLContext.getInstance("TLS").apply { init(km.keyManagers,tm.trustManagers,null) }
        val server=tls.serverSocketFactory.createServerSocket(0,1,java.net.InetAddress.getByName("127.0.0.1"))
        server.soTimeout=3000
        val accepted=java.util.concurrent.atomic.AtomicReference<java.net.Socket?>()
        val serverError=java.util.concurrent.atomic.AtomicReference<Throwable?>()
        val thread=Thread {
            try { server.accept().use { socket ->
                accepted.set(socket);socket.soTimeout=3000
                val input=socket.getInputStream().bufferedReader();val headers=mutableListOf<String>()
                while(true) { val line=input.readLine() ?: error("EOF");if(line.isEmpty()) break;headers.add(line) }
                assertEquals("GET /v2/voice HTTP/1.1",headers.first())
                val key=headers.single { it.startsWith("Sec-WebSocket-Key:",true) }.substringAfter(':').trim()
                val accept=java.util.Base64.getEncoder().encodeToString(java.security.MessageDigest.getInstance("SHA-1").digest((key+"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").toByteArray()))
                socket.getOutputStream().write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: "+accept+"\r\n\r\n").toByteArray())
                // Wait for client cancellation; no application payload or credential is sent.
                try { socket.getInputStream().read() } catch(_:IOException) { }
            } } catch(e:Throwable) { serverError.set(e) }
        }
        val factory=object:javax.net.SocketFactory() {
            override fun createSocket()=V2MappedSocket { server.localPort }
            override fun createSocket(h:String,p:Int):java.net.Socket=error("unsupported")
            override fun createSocket(h:String,p:Int,l:java.net.InetAddress,lp:Int):java.net.Socket=error("unsupported")
            override fun createSocket(h:java.net.InetAddress,p:Int):java.net.Socket=error("unsupported")
            override fun createSocket(h:java.net.InetAddress,p:Int,l:java.net.InetAddress,lp:Int):java.net.Socket=error("unsupported")
        }
        val client=OkHttpClient.Builder().proxy(Proxy.NO_PROXY).retryOnConnectionFailure(false).socketFactory(factory).sslSocketFactory(tls.socketFactory,trust).build()
        val done=java.util.concurrent.CountDownLatch(1);val error=java.util.concurrent.atomic.AtomicReference<Throwable?>()
        thread.start()
        val ws=client.newWebSocket(Request.Builder().url("wss://127.0.0.1:19483/v2/voice").build(),object:okhttp3.WebSocketListener() {
            override fun onOpen(w:okhttp3.WebSocket,r:okhttp3.Response) { done.countDown() }
            override fun onFailure(w:okhttp3.WebSocket,t:Throwable,r:okhttp3.Response?) { error.set(t);done.countDown() }
        })
        try { assertTrue(done.await(5,java.util.concurrent.TimeUnit.SECONDS));error.get()?.let { throw AssertionError(it) } }
        finally { ws.cancel();accepted.get()?.close();server.close();thread.join(4000);client.connectionPool.evictAll();client.dispatcher.executorService.shutdownNow() }
        assertFalse(thread.isAlive);serverError.get()?.let { throw AssertionError(it) }
    }
    private val token="a".repeat(32)
    private val public=File("src/v2Debug/assets/v2-transport").takeIf { it.isDirectory }
        ?: File("app/src/v2Debug/assets/v2-transport")
    private fun profile() : V2SshProfile {
        val p=Properties().apply { File(public,"ssh.properties").inputStream().use { load(it) } }
        return V2SshProfile(p.getProperty("host"),"v2-device-unit",p.getProperty("hostKey"),
            V2SshProfile.trustFor(File(public,"ca.pem").readBytes()))
    }
    private fun rejects(block:()->Unit) { try { block();fail("accepted unsafe configuration") } catch(_:IllegalArgumentException) {} }
    @Test fun exactSshAddressAndDedicatedAccount() {
        assertEquals("v2-device-unit",ParentConnection("wss://127.0.0.1:19483/v2/voice",token,"v2-device-unit").sshUser)
        for(a in listOf("wss://127.0.0.1:19443/v2/voice","wss://localhost:19483/v2/voice","wss://127.0.0.1:19483/v1/animal","wss://example.com/v2/voice"))
            rejects { ParentConnection(a,token,"v2-device-unit") }
        for(u in listOf("root","little-buddy-device","a;id","", "a/b")) rejects { ParentConnection("wss://127.0.0.1:19483/v2/voice",token,u) }
    }
    @Test fun noFalseDirectLoopback() {
        for(a in listOf("wss://localhost:19483/v2/voice","wss://127.0.0.1:19483/v2/voice")) rejects { ParentConnection(a,token).requireRunnable() }
        ParentConnection("wss://issued.example/v2/voice",token)
    }
    @Test fun codecRoundTripPreservesModeWithoutCredentialDisplay() {
        val c=ParentConnection("wss://127.0.0.1:19483/v2/voice",token,"v2-device-unit")
        val decoded=ParentCodec.decode(ParentCodec.encode(ParentRecord(ByteArray(16),ByteArray(32),0,0,60,connection=c)))
        assertEquals(c.sshUser,decoded.connection!!.sshUser);assertEquals(token,decoded.connection!!.credential)
        assertFalse(c.toString().contains(token))
    }
    @Test fun legacyLoopbackRecordRemainsReadableButCannotStart() {
        val old=ParentConnection("wss://127.0.0.1:19483/v2/voice",token)
        val decoded=ParentCodec.decode(ParentCodec.encode(ParentRecord(ByteArray(16),ByteArray(32),0,0,60,connection=old)))
        rejects { decoded.connection!!.requireRunnable() }
    }
    @Test fun pinnedHostAndSshPortRejectChanges() {
        val p=profile();rejects { V2SshProfile(p.host,p.user,p.hostKey,p.trust,2222) }
        rejects { V2SshProfile(p.host,p.user,p.hostKey.dropLast(4)+"AAAA",p.trust) }
        rejects { V2SshProfile(p.host,"root",p.hostKey,p.trust) }
    }
    @Test fun proxyRedirectRetryAndHostnameDefaultsRemainClosed() {
        val base=OkHttpClient();val ssh=V2Ssh(profile());val c=ssh.client(base)
        assertEquals(Proxy.NO_PROXY,c.proxy);assertFalse(c.followRedirects);assertFalse(c.followSslRedirects)
        assertFalse(c.retryOnConnectionFailure);assertSame(base.hostnameVerifier,c.hostnameVerifier)
        assertEquals(1,profile().trust.acceptedIssuers.size);ssh.close()
    }
    @Test fun wrongWssRequestNeverOpensTunnel() {
        val ssh=V2Ssh(profile());val c=ssh.client(OkHttpClient())
        for(a in listOf("https://127.0.0.1:19443/v2/voice","https://127.0.0.1:19483/v1/animal","https://example.com:19483/v2/voice","https://127.0.0.1:19483/v2/voice?q=1")) {
            try { c.newCall(Request.Builder().url(a).build()).execute();fail("bypass") }
            catch(e:IOException) { assertEquals("Unexpected V2 WSS target",e.message) }
        }
        ssh.close()
    }
    @Test fun closeBeforeOpenAndRepeatedCloseRejectsReopening() {
        val ssh=V2Ssh(profile());ssh.close();ssh.close()
        try { ssh.open();fail("reopened") } catch(_:IllegalStateException) {}
    }
    @Test fun independentIdentityAndPublicAssetBoundary() {
        assertEquals("buddy-ssh-device-v2",V2SshIdentity.ALIAS)
        val p=Properties().apply { File(public,"ssh.properties").inputStream().use { load(it) } }
        assertEquals(setOf("host","hostKey"),p.stringPropertyNames())
        assertEquals(19483,V2SshProfile.PORT);assertEquals("/v2/voice",V2SshProfile.endpoint.encodedPath)
    }
    @Test fun exportFinalDecisionUsesWorkerAndHomeSuppressesLatePublicMaterial() {
        for (stage in 0..2) {
            var inUi=false
            val store=object:ParentStore {
                var value:ParentRecord?=null
                override fun read()=value
                override fun write(record:ParentRecord,authorized:()->Boolean) { check(authorized());value=record }
            }
            val d=ParentDomain(store,{100L},{check(!inUi)},object:OwnerProof {
                override fun consume(challenge:OwnerChallenge)=true
            },"export-test")
            val page=d.enterPage();check(d.replacePin("012345".toCharArray(),d.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN,page)!!,page))
            val work=java.util.ArrayDeque<()->Unit>();val ui=java.util.ArrayDeque<()->Unit>()
            val m=ParentPanelModel({d},{work.add(it)},{ui.add(it)},{},{})
            fun drain() { while(work.isNotEmpty() || ui.isNotEmpty()) {
                while(work.isNotEmpty())work.removeFirst()()
                while(ui.isNotEmpty()) { inUi=true;try { ui.removeFirst()() } finally { inUi=false } }
            } }
            m.open();drain();m.verify("012345".toCharArray());drain()
            var delivered=0
            m.exportTransportKey({ if(stage==1)m.pause();"PUBLIC ONLY" }) { delivered++ }
            if(stage==2) { while(work.isNotEmpty())work.removeFirst()();m.pause() }
            drain();assertEquals(if(stage==0)1 else 0,delivered)
        }
    }
    @Test fun exportBeforeGrantDoesNotGenerateKey() {
        var generated=0
        val m=ParentPanelModel({null},{it()},{it()},{},{})
        m.open();m.exportTransportKey({generated++;"PUBLIC"}){fail("unverified export")}
        assertEquals(0,generated)
    }

}
