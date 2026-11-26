package com.littlebuddy

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.file.Files
import java.security.KeyStore
import java.security.cert.CertificateFactory
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

/** Opt-in integration with the actual local TLS fixture, without Android native audio. */
class GameReleaseIntegrationTest {
    @Test fun ackCanTraverseTheSocketWhileTheNextSegmentHasNoConsumer() {
        releaseProbe(delayedProducer = false)
    }

    @Test fun delayedProducerCannotLetConfirmationOvertakeTheBlockedFrame() {
        releaseProbe(delayedProducer = true)
    }

    private fun releaseProbe(delayedProducer: Boolean) {
        assumeTrue(System.getenv("ANIMAL_RELEASE_PROBE") == "1")
        val directory = Files.createTempDirectory("animal-release-probe").toFile()
        val cert = File(directory, "cert.pem")
        val key = File(directory, "key.pem")
        val openssl = ProcessBuilder("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
            "-days", "1", "-out", cert.path, "-keyout", key.path)
            .redirectErrorStream(true).redirectOutput(File(directory, "openssl.log")).start()
        try {
            assertTrue(openssl.waitFor(5, TimeUnit.SECONDS))
            assertEquals(0, openssl.exitValue())
            // Separate, joined fixture processes avoid a connection-retirement sleep.
            for (bufferEntireSegment in listOf(false, true)) {
                val portFile = File(directory, "port-$bufferEntireSegment")
                val server = ProcessBuilder("python3", "-c", """
                    import asyncio, pathlib, ssl, sys
                    from backend.animal.private_fixture import fixture_server
                    import backend.animal.cloud as cloud
                    class ReleaseBarrierChannel(cloud.GameChannel):
                        def __init__(self, socket):
                            super().__init__(socket)
                            self.segment = 0
                            self.second_frames = 0
                            self.fifth_sent = asyncio.Event()
                        async def control(self, kind, **fields):
                            if kind == "segment.start":
                                self.segment = fields["number"]
                                if self.key.turn_id == 2 and self.segment == 2 and sys.argv[4] == "true":
                                    # Adversarial scheduling, not the synchronization mechanism.
                                    await asyncio.sleep(.35)
                            if kind == "playback.segment_committed" and self.key.turn_id == 2 and fields["number"] == 1:
                                # Queue the confirmation only AFTER the fifth binary write.
                                # That frame blocks the legacy reader's capacity-four queue.
                                async with asyncio.timeout(5):
                                    await self.fifth_sent.wait()
                            await super().control(kind, **fields)
                        async def send(self, data):
                            await super().send(data)
                            if self.key.turn_id == 2 and self.segment == 2 and isinstance(data, bytes):
                                self.second_frames += 1
                                if self.second_frames == 5:
                                    self.fifth_sent.set()
                    cloud.GameChannel = ReleaseBarrierChannel
                    async def run():
                        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                        tls.load_cert_chain(sys.argv[1], sys.argv[2])
                        async with fixture_server(0, tls, "offlinefixture" * 3, "release") as listener:
                            pathlib.Path(sys.argv[3]).write_text(str(listener.sockets[0].getsockname()[1]))
                            await asyncio.Future()
                    asyncio.run(run())
                    """.trimIndent(), cert.path, key.path, portFile.path, delayedProducer.toString())
                    .directory(File("..").canonicalFile).redirectErrorStream(true)
                    .redirectOutput(File(directory, "fixture.log")).start()
                try {
                    val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5)
                    var port: Int? = null
                    while (port == null && server.isAlive && System.nanoTime() < deadline) {
                        port = if (portFile.exists()) portFile.readText().toIntOrNull() else null
                        if (port == null) Thread.sleep(20)
                    }
                    assertNotNull("loopback fixture startup", port)
                    probe(checkNotNull(port), cert, bufferEntireSegment)
                } finally {
                    server.destroy()
                    if (!server.waitFor(3, TimeUnit.SECONDS)) {
                        server.destroyForcibly()
                        assertTrue("fixture process must exit", server.waitFor(3, TimeUnit.SECONDS))
                    }
                }
            }
        } finally {
            if (openssl.isAlive) openssl.destroyForcibly()
            directory.deleteRecursively()
        }
    }

    private fun probe(port: Int, cert: File, bufferEntireSegment: Boolean) {
        val certificate = cert.inputStream().use { CertificateFactory.getInstance("X.509").generateCertificate(it) }
        val store = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
            load(null)
            setCertificateEntry("fixture", certificate)
        }
        val trust = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply { init(store) }
            .trustManagers.single() as X509TrustManager
        val tls = SSLContext.getInstance("TLS").apply { init(null, arrayOf(trust), null) }
        val client = OkHttpClient.Builder().sslSocketFactory(tls.socketFactory, trust).build()
        val done = CountDownLatch(1)
        var confirmed = false
        var framesAheadOfConfirmation = 0
        var framesAtConfirmation = -1
        var failure: Throwable? = null
        val socket = client.newWebSocket(Request.Builder().url("wss://127.0.0.1:$port/v1/animal")
            .header("Authorization", "Bearer ${"offlinefixture".repeat(3)}").build(), object : WebSocketListener() {
            private lateinit var key: String
            private var turn = 0
            private var segment = 0
            private lateinit var stream: CloudPcm
            private fun value(message: String, field: String) =
                Regex(""""$field"\s*:\s*(\d+)""").find(message)!!.groupValues[1].toInt()

            override fun onOpen(ws: WebSocket, response: Response) {
                ws.send("""{"event":"session.start","v":1,"catalog":"animal-click-1","images":["animal-dog","animal-cat","animal-duck","animal-rabbit","animal-elephant","animal-giraffe"]}""")
            }

            override fun onMessage(ws: WebSocket, message: String) = checkMessage {
                when (Regex(""""event"\s*:\s*"([^"]+)"""").find(message)!!.groupValues[1]) {
                    "reply" -> {
                        key = Regex(""""key"\s*:\s*(\{[^}]+})""").find(message)!!.groupValues[1]
                        turn = value(key, "turn_id")
                    }
                    "segment.start" -> {
                        segment = value(message, "number")
                        stream = CloudPcm({ _, _ -> }, bufferEntireSegment = bufferEntireSegment)
                    }
                    "segment.end" -> {
                        stream.seal(value(message, "samples"))
                        if (segment == 1) {
                            assertTrue(stream.ended)
                            ws.send("""{"event":"playback.segment_completed","key":$key,"number":1}""")
                        }
                    }
                    "turn.committed" -> if (turn == 1) {
                        val permit = Regex(""""listen_id"\s*:\s*"([^"]+)"""").find(message)!!.groupValues[1]
                        ws.send("""{"event":"turn.start","key":$key,"listen_id":"$permit"}""")
                    }
                    "turn.ready" -> {
                        ws.send(ByteBuffer.allocate(646).put(1).put(1).putInt(0).array().toByteString())
                        ws.send("""{"v":1,"type":"turn.end","samples":320}""")
                    }
                    "playback.segment_committed" -> if (turn == 2 && value(message, "number") == 1) {
                        val receiptKey = Regex(""""key"\s*:\s*(\{[^}]+})""").find(message)!!.groupValues[1]
                        assertEquals("confirmation must belong to the first segment's reply", key, receiptKey)
                        framesAtConfirmation = framesAheadOfConfirmation
                        confirmed = true
                        done.countDown()
                    }
                }
                Unit
            }

            override fun onMessage(ws: WebSocket, bytes: ByteString) = checkMessage {
                if (turn == 2 && segment == 2) framesAheadOfConfirmation++
                stream.push(bytes.toByteArray())
                if (segment == 1) assertNotNull(stream.poll())
            }

            private fun checkMessage(block: () -> Unit) {
                // A queued receipt after the timeout must not mutate the terminal result.
                if (done.count == 0L) return
                try {
                    block()
                } catch (error: Throwable) {
                    failure = error
                    done.countDown()
                }
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                if (done.count > 0) {
                    failure = t
                    done.countDown()
                }
            }
        })
        try {
            assertTrue("fixture websocket did not complete", done.await(10, TimeUnit.SECONDS))
            assertTrue("fixture must transmit over four queued frames before confirmation",
                framesAheadOfConfirmation > 4)
            println("RELEASE_ORDER entire=$bufferEntireSegment frames=$framesAheadOfConfirmation receipt_frames=$framesAtConfirmation confirmed=$confirmed failure=${failure?.javaClass?.simpleName}")
            if (bufferEntireSegment) {
                failure?.let { throw AssertionError("bounded game buffering failed", it) }
                assertTrue(confirmed)
                assertTrue("first confirmation must follow the fifth frame on the wire", framesAtConfirmation >= 5)
            } else {
                assertFalse(confirmed)
                assertTrue("legacy queue must time out on an unconsumed frame", failure is IllegalStateException)
            }
        } finally {
            socket.cancel()
            client.dispatcher.executorService.shutdown()
            client.connectionPool.evictAll()
        }
    }
}
