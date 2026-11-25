package com.littlebuddy.v2.feedback
import org.junit.Assert.*
import org.junit.Test
import com.littlebuddy.v2.transport.*
import com.littlebuddy.v2.transport.Target
import java.net.InetSocketAddress

class FeedbackTransportContractTest {
    @Test fun uuidV7BindsOriginalMillisecondsAndRandomVersionVariant() {
        val at=1_800_000_000_123L;val values=(1..100).map { FeedbackKeys.create(at) }
        assertEquals(100,values.toSet().size)
        for(value in values) {val id=FeedbackKeys.checked(value,true);assertEquals(7,id.version());assertEquals(2,id.variant());assertEquals(at,id.mostSignificantBits ushr 16)}
    }
    @Test fun legacyV4CanOnlyReadWithdrawNotNewSubmit() {
        val old=java.util.UUID.randomUUID().toString();FeedbackKeys.checked(old)
        try {FeedbackKeys.checked(old,true);fail("v4 resubmitted")}catch(e:FeedbackFailure){assertEquals(Failure.INVALID,e.reason)}
    }
    @Test fun strictJsonRejectsDuplicateKeysFractionalTimesAndTrailingDocuments() {
        for(text in listOf("{\"v\":1,\"v\":1}","{\"v\":1.0}","{\"v\":1}{}","{\"v\":1,}","[]")) {
            try {FeedbackJson.parse(text);fail("permissive receipt: $text")}catch(_:Exception){}
        }
        assertEquals(1L,FeedbackJson.parse("{\"v\":1}")["v"])
    }
    @Test fun targetsAreExactlyVoiceAndFeedbackWithSameRemoteEndpoint() {
        assertEquals(setOf("/v2/voice","/v2/feedback"),Target.entries.map{it.path}.toSet())
        assertEquals(19483,V2SshProfile.PORT);assertEquals("127.0.0.1",V2SshProfile.LOOPBACK)
    }
    @Test fun ownedEphemeralMappingsDoNotCollideAndCannotChangeLogicalTarget() {
        val logical=InetSocketAddress("127.0.0.1",19483)
        assertEquals(22001,V2Forwarding.mapped(logical,22001).port);assertEquals(22002,V2Forwarding.mapped(logical,22002).port)
        for(bad in listOf(InetSocketAddress("127.0.0.1",19443),InetSocketAddress("192.0.2.1",19483))) {
            try {V2Forwarding.mapped(bad,22001);fail("arbitrary forwarding")}catch(_:java.io.IOException){}
        }
    }
    @Test fun replyParserBoundsMaterialAndDepth() {
        for(text in listOf("{\"x\":{\"y\":{\"z\":1}}}","{\"x\":\""+"a".repeat(400001)+"\"}")) {
            try {FeedbackJson.parse(text);fail("unbounded receipt")}catch(_:Exception){}
        }
    }    @Test fun bothTargetInterceptorsAcceptOnlyTheirExactPinnedLogicalRoute() {
        val directory=java.io.File("src/v2Debug/assets/v2-transport").takeIf { it.isDirectory }
            ?: java.io.File("app/src/v2Debug/assets/v2-transport")
        val properties=java.util.Properties().apply {java.io.File(directory,"ssh.properties").inputStream().use{load(it)}}
        val profile=V2SshProfile(properties.getProperty("host"),"v2-feedback-fixture",properties.getProperty("hostKey"),
            V2SshProfile.trustFor(java.io.File(directory,"ca.pem").readBytes()))
        for(target in Target.entries) {
            val ssh=V2Ssh(profile);val http=ssh.client(okhttp3.OkHttpClient(),target);var proceeded=0
            fun invoke(url:String) {
                val request=okhttp3.Request.Builder().url(url).build()
                val chain=java.lang.reflect.Proxy.newProxyInstance(okhttp3.Interceptor.Chain::class.java.classLoader,
                    arrayOf(okhttp3.Interceptor.Chain::class.java)) { _,method,args->when(method.name) {
                        "request"->request
                        "proceed"->{proceeded++;okhttp3.Response.Builder().request(args!![0] as okhttp3.Request)
                            .protocol(okhttp3.Protocol.HTTP_1_1).code(101).message("synthetic").build()}
                        else->error("unexpected chain call")
                    } } as okhttp3.Interceptor.Chain
                http.interceptors.last().intercept(chain)
            }
            invoke("https://127.0.0.1:19483"+target.path);assertEquals(1,proceeded)
            val other=if(target==Target.VOICE)Target.FEEDBACK else Target.VOICE
            for(url in listOf("https://127.0.0.1:19483"+other.path,"https://127.0.0.1:19443"+target.path,"https://127.0.0.1:19483"+target.path+"?q=1")) {
                try {invoke(url);fail("arbitrary route")}catch(_:java.io.IOException){}
            }
            assertEquals(1,proceeded);assertEquals(java.net.Proxy.NO_PROXY,http.proxy)
            assertFalse(http.followRedirects);assertFalse(http.followSslRedirects);assertFalse(http.retryOnConnectionFailure);ssh.close()
        }
    }

}
