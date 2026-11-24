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
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import java.util.Collections
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

/** Opt-in integration with the actual local TLS fixture, without Android native audio. */
class GameReleaseIntegrationTest {
    @Test fun ackCanTraverseTheSocketWhileTheNextSegmentHasNoConsumer() {
        assumeTrue(System.getenv("ANIMAL_RELEASE_PROBE") == "1")
        val directory = Files.createTempDirectory("animal-release-probe").toFile()
        val cert = File(directory, "cert.pem")
        val key = File(directory, "key.pem")
        val portFile = File(directory, "port")
        val openssl = ProcessBuilder("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
            "-days", "1", "-out", cert.path, "-keyout", key.path)
            .redirectErrorStream(true).redirectOutput(File(directory, "openssl.log")).start()
        try {
            assertTrue(openssl.waitFor(5, TimeUnit.SECONDS))
            assertEquals(0, openssl.exitValue())
            for (serviceDelayMs in listOf(0, 500)) {
                portFile.delete()
                val server = ProcessBuilder("python3", "-c", """
                    import asyncio, pathlib, ssl, sys
                    from contextlib import asynccontextmanager
                    from backend.animal.private_fixture import Fixture
                    original = Fixture.synthesize
                    @asynccontextmanager
                    async def delayed(self, segment, rate):
                        async with original(self, segment, rate) as frames:
                            async def output():
                                index = 0
                                async for frame in frames:
                                    index += 1
                                    if index == 5:
                                        await asyncio.sleep(int(sys.argv[4]) / 1000)
                                    yield frame
                            yield output()
                    Fixture.synthesize = delayed
                    from backend.animal.private_fixture import fixture_server
                    async def run():
                        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                        tls.load_cert_chain(sys.argv[1], sys.argv[2])
                        async with fixture_server(0, tls, "offlinefixture" * 3, "release") as listener:
                            pathlib.Path(sys.argv[3]).write_text(str(listener.sockets[0].getsockname()[1]))
                            await asyncio.Future()
                    asyncio.run(run())
                    """.trimIndent(), cert.path, key.path, portFile.path, serviceDelayMs.toString())
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
                    for (ackDelayMs in listOf(0, 200)) {
                        probe(checkNotNull(port), cert, false, serviceDelayMs, ackDelayMs)
                        probe(port, cert, true, serviceDelayMs, ackDelayMs)
                    }
                } finally {
                    server.destroy()
                    if (!server.waitFor(3, TimeUnit.SECONDS)) {
                        server.destroyForcibly()
                        server.waitFor(3, TimeUnit.SECONDS)
                    }
                }
            }
        } finally {
            if (openssl.isAlive) openssl.destroyForcibly()
            directory.deleteRecursively()
        }
    }

    private fun probe(port: Int, cert: File, bufferEntireSegment: Boolean, serviceDelayMs: Int, ackDelayMs: Int) {
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
        val confirmed = AtomicBoolean(false)
        val failure = AtomicReference<Throwable?>(null)
        val fifthFrame = CountDownLatch(1)
        val ackSent = CountDownLatch(1)
        val pendingAck = AtomicReference<String?>(null)
        val liveSocket = AtomicReference<WebSocket?>(null)
        val timeline = Collections.synchronizedList(mutableListOf<String>())
        fun event(name: String) { timeline.add("$name ns=${System.nanoTime()}") }
        var ackPendingAt = 0L
        var fifthAt = 0L
        var framesBeforeAckBarrier = 0 // Reader-owned; frozen at the fifth frame.
        val ackWorker = Thread({
            try {
                check(fifthFrame.await(5, TimeUnit.SECONDS)) { "fifth frame not observed" }
                if (ackDelayMs > 0) Thread.sleep(ackDelayMs.toLong())
                check(!confirmed.get())
                event("ACK_SEND")
                check(checkNotNull(liveSocket.get()).send(checkNotNull(pendingAck.get())))
                ackSent.countDown()
            } catch (error: Throwable) {
                failure.compareAndSet(null, error)
                done.countDown()
            }
        }, "fixture-ack-driver")
        val socket = client.newWebSocket(Request.Builder().url("wss://127.0.0.1:$port/v1/animal")
            .header("Authorization", "Bearer ${"offlinefixture".repeat(3)}").build(), object : WebSocketListener() {
            private lateinit var key: String
            private var turn = 0
            private var segment = 0
            private lateinit var stream: CloudPcm
            private fun value(message: String, field: String) =
                Regex(""""$field"\s*:\s*(\d+)""").find(message)!!.groupValues[1].toInt()

            override fun onOpen(ws: WebSocket, response: Response) {
                liveSocket.set(ws)
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
                            val ack = """{"event":"playback.segment_completed","key":$key,"number":1}"""
                            if (turn == 2) {
                                ackPendingAt = System.nanoTime()
                                pendingAck.set(ack)
                                event("ACK_PENDING")
                            } else check(ws.send(ack))
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
                    "playback.segment_committed" -> if (turn == 2) {
                        event("ACK_RECEIVED")
                        confirmed.set(true)
                        done.countDown()
                    }
                }
                Unit
            }

            override fun onMessage(ws: WebSocket, bytes: ByteString) = checkMessage {
                if (turn == 2 && segment == 2 && fifthFrame.count > 0) {
                    framesBeforeAckBarrier++
                    if (framesBeforeAckBarrier == 5) {
                        assertFalse("fifth unconsumed frame precedes real ACK", confirmed.get())
                        assertNotNull(pendingAck.get())
                        fifthAt = System.nanoTime()
                        event("FIFTH_FRAME_BEFORE_PUSH confirmed=false frame=5")
                        fifthFrame.countDown()
                    }
                }
                stream.push(bytes.toByteArray())
                if (segment == 1) assertNotNull(stream.poll())
            }

            private fun checkMessage(block: () -> Unit) {
                // First terminal event owns the result; late callbacks cannot revive a failed stream.
                if (done.count == 0L) return
                try {
                    block()
                } catch (error: Throwable) {
                    event("READER_FAILED class=${error.javaClass.simpleName}")
                    failure.compareAndSet(null, error)
                    done.countDown()
                }
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                if (done.count > 0) {
                    failure.compareAndSet(null, t)
                    done.countDown()
                }
            }
        })
        try {
            ackWorker.start()
            assertTrue("fixture websocket did not complete", done.await(10, TimeUnit.SECONDS))
            assertTrue("fixture must transmit over four queued frames before confirmation",
                framesBeforeAckBarrier > 4)
            assertTrue("same socket ACK driver sent after fifth frame", ackSent.await(1, TimeUnit.SECONDS))
            assertTrue("service delay must really precede frame five",
                fifthAt - ackPendingAt >= TimeUnit.MILLISECONDS.toNanos(serviceDelayMs.toLong()))
            if (bufferEntireSegment) {
                failure.get()?.let { throw AssertionError("bounded game buffering failed", it) }
                assertTrue(confirmed.get())
            } else {
                assertFalse(confirmed.get())
                assertTrue("legacy queue must time out on an unconsumed frame", failure.get() is IllegalStateException)
            }
        } finally {
            socket.cancel()
            ackWorker.interrupt()
            ackWorker.join(3000)
            client.dispatcher.executorService.shutdown()
            client.connectionPool.evictAll()
            assertFalse("ACK driver must retire", ackWorker.isAlive)
            assertTrue("socket workers must retire", client.dispatcher.executorService.awaitTermination(5, TimeUnit.SECONDS))
            println("TLS_RELEASE buffer=$bufferEntireSegment serviceDelay=$serviceDelayMs ackDelay=$ackDelayMs frames=$framesBeforeAckBarrier confirmed=${confirmed.get()} events=$timeline")
        }
    }
}
