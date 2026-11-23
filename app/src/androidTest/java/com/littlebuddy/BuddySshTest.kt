package com.littlebuddy

import android.util.Base64
import androidx.test.platform.app.InstrumentationRegistry
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException
import java.net.InetAddress
import java.net.ServerSocket
import java.security.KeyStore
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class BuddySshTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val args get() = InstrumentationRegistry.getArguments()
    private val base = OkHttpClient.Builder().retryOnConnectionFailure(false)
        .followRedirects(false).followSslRedirects(false).build()

    private fun profile(key: String = checkNotNull(args.getString("sshKey")), ca: String = "ssh-ca.pem") =
        BuddySshProfile("127.0.0.1", checkNotNull(args.getString("sshUser")), key,
            BuddySshProfile.trustFor(context.filesDir.resolve(ca).readBytes()), 19442)

    @Test fun exportOnlyIndependentPublicKey() {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val first = BuddySshIdentity.load(create = true)
        val entry = store.getEntry(BuddySshIdentity.ALIAS, null) as KeyStore.PrivateKeyEntry
        assertNull(entry.privateKey.encoded)
        assertNull(first.getSignature(byteArrayOf(1), "ssh-rsa"))
        store.deleteEntry(BuddySshIdentity.ALIAS)
        val second = BuddySshIdentity.load(create = true)
        assertNotEquals(first.registrationKey(), second.registrationKey())
        context.filesDir.resolve("ssh-device.pub").writeText(second.registrationKey() + "\n")
    }

    @Test fun authenticatedWssReopensAfterClose() {
        repeat(2) {
            BuddySsh(profile()).use { tunnel ->
                assertEquals(101, upgrade(tunnel, "offlinefixture".repeat(3)))
            }
        }
    }

    @Test fun tlsAndTokenAreStillRequired() {
        BuddySsh(profile()).use { assertEquals(401, upgrade(it, null)) }
        BuddySsh(profile()).use { assertEquals(401, upgrade(it, "x".repeat(48))) }
        BuddySsh(profile(ca = "ssh-wrong-ca.pem")).use { assertEquals(-1, upgrade(it, null)) }
        BuddySsh(profile()).use { assertEquals(-1, upgrade(it, null, "https://127.0.0.1:19444/v1/animal")) }
    }

    @Test fun rejectsWrongHostKeyAndOccupiedLocalPort() {
        val bytes = Base64.decode(checkNotNull(args.getString("sshKey")), Base64.DEFAULT)
        bytes[bytes.lastIndex] = (bytes.last().toInt() xor 1).toByte()
        BuddySsh(profile(Base64.encodeToString(bytes, Base64.NO_WRAP))).use {
            assertEquals(-1, upgrade(it, null))
        }
        ServerSocket(19443, 1, InetAddress.getByName("127.0.0.1")).use {
            BuddySsh(profile()).use { tunnel -> assertEquals(-1, upgrade(tunnel, null)) }
        }
        BuddySsh(profile()).use { assertEquals(101, upgrade(it, "offlinefixture".repeat(3))) }
    }

    @Test fun closeInterruptsHandshakeAndAllowsFreshTunnel() {
        val executor = Executors.newSingleThreadExecutor()
        try {
            ServerSocket(0, 1, InetAddress.getByName("127.0.0.1")).use { blackhole ->
                val fixture = profile()
                BuddySsh(BuddySshProfile(fixture.host, fixture.user, fixture.hostKey,
                    fixture.trust, blackhole.localPort)).use { tunnel ->
                    val result = executor.submit<Int> { upgrade(tunnel, null) }
                    blackhole.soTimeout = 4_000
                    blackhole.accept().use {
                        tunnel.close()
                        assertEquals(-1, result.get(3, TimeUnit.SECONDS))
                    }
                }
            }
            BuddySsh(profile()).use { assertEquals(101, upgrade(it, "offlinefixture".repeat(3))) }
        } finally {
            executor.shutdownNow()
        }
    }

    @Test fun rejectsInvalidServerCertificate() {
        BuddySsh(profile()).use { assertEquals(-1, upgrade(it, "offlinefixture".repeat(3))) }
    }

    @Test fun replacedDeviceTokenCannotStartAnotherSession() {
        val old = "offlinefixture".repeat(3)
        BuddySsh(profile()).use { assertEquals(101, upgrade(it, old)) }
        BuddySsh(profile()).use { assertEquals(401, upgrade(it, old)) }
        BuddySsh(profile()).use { assertEquals(101, upgrade(it, "rotatedfixture".repeat(3))) }
    }

    @Test fun revokedDeviceKeyCannotAuthenticate() {
        BuddySsh(profile()).use { assertEquals(-1, upgrade(it, "offlinefixture".repeat(3))) }
    }

    private fun upgrade(tunnel: BuddySsh, token: String?, url: String = BuddySshProfile.endpoint.toString()): Int {
        val request = Request.Builder().url(url).apply {
            if (token != null) header("Authorization", "Bearer $token")
        }.build()
        val client = tunnel.client(base)
        val terminal = CountDownLatch(1)
        var code = -2
        val socket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                code = response.code
                terminal.countDown()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                code = response?.code ?: -1
                assertTrue(t is IOException)
                terminal.countDown()
            }
        })
        try {
            assertTrue("WSS callback timed out", terminal.await(10, TimeUnit.SECONDS))
            return code
        } finally {
            socket.cancel()
            client.connectionPool.evictAll()
        }
    }
}
