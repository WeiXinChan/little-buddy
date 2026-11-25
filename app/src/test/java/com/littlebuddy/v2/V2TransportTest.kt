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
