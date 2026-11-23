package com.littlebuddy

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import com.jcraft.jsch.Identity
import com.jcraft.jsch.JSch
import com.jcraft.jsch.Session
import com.jcraft.jsch.SocketFactory
import okhttp3.ConnectionPool
import okhttp3.OkHttpClient
import okhttp3.HttpUrl.Companion.toHttpUrl
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.SocketAddress
import java.net.Proxy
import java.net.Socket
import java.net.SocketException
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.Signature
import java.security.cert.CertificateFactory
import java.security.interfaces.RSAPublicKey
import java.util.Properties
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

internal class BuddySshIdentity private constructor(
    private val key: PrivateKey,
    publicKey: RSAPublicKey,
) : Identity {
    private val blob = encode(ALGORITHM.toByteArray(), publicKey.publicExponent.toByteArray(),
        publicKey.modulus.toByteArray())

    override fun getPublicKeyBlob() = blob.copyOf()
    override fun getAlgName() = ALGORITHM
    override fun getName() = ALIAS
    override fun isEncrypted() = false
    override fun setPassphrase(passphrase: ByteArray?) = false
    override fun clear() = Unit
    override fun getSignature(data: ByteArray): ByteArray? = null
    override fun getSignature(data: ByteArray, algorithm: String): ByteArray? {
        if (algorithm != SIGNATURE) return null
        val signature = Signature.getInstance("SHA256withRSA").run {
            initSign(key)
            update(data)
            sign()
        }
        return encode(SIGNATURE.toByteArray(), signature)
    }

    fun registrationKey() = "$ALGORITHM ${Base64.encodeToString(blob, Base64.NO_WRAP)}"

    companion object {
        internal const val ALIAS = "buddy-ssh-device-v1"
        private const val ALGORITHM = "ssh-rsa"
        internal const val SIGNATURE = "rsa-sha2-256"

        @Synchronized
        fun load(create: Boolean = false): BuddySshIdentity {
            val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            if (create && !store.containsAlias(ALIAS)) {
                KeyPairGenerator.getInstance("RSA", "AndroidKeyStore").apply {
                    initialize(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
                        .setKeySize(2048)
                        .setDigests(KeyProperties.DIGEST_SHA256)
                        .setSignaturePaddings(KeyProperties.SIGNATURE_PADDING_RSA_PKCS1)
                        .build())
                }.generateKeyPair()
            }
            val entry = store.getEntry(ALIAS, null) as KeyStore.PrivateKeyEntry
            return BuddySshIdentity(entry.privateKey, entry.certificate.publicKey as RSAPublicKey)
        }

        private fun encode(vararg fields: ByteArray): ByteArray {
            val bytes = ByteArrayOutputStream()
            DataOutputStream(bytes).use { output ->
                fields.forEach {
                    output.writeInt(it.size)
                    output.write(it)
                }
            }
            return bytes.toByteArray()
        }
    }
}

internal class BuddySshProfile(
    val host: String,
    val user: String,
    val hostKey: String,
    val trust: X509TrustManager,
    val sshPort: Int = 22,
) {
    companion object {
        const val LOOPBACK = "127.0.0.1"
        const val PORT = 19443
        val endpoint = "https://$LOOPBACK:$PORT/v1/animal".toHttpUrl()

        fun load(context: Context): BuddySshProfile {
            val properties = Properties().apply {
                context.assets.open("transport/ssh.properties").use { load(it) }
            }
            val host = properties.getProperty("host")
            val user = properties.getProperty("user")
            val hostKey = properties.getProperty("hostKey")
            val ca = context.assets.open("transport/ca.pem").use { it.readBytes() }
            return BuddySshProfile(host, user, hostKey, trustFor(ca))
        }

        internal fun trustFor(ca: ByteArray): X509TrustManager {
            val certificate = CertificateFactory.getInstance("X.509")
                .generateCertificate(ca.inputStream()) as java.security.cert.X509Certificate
            require(certificate.basicConstraints >= 0)
            certificate.checkValidity()
            val trusted = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
                load(null)
                setCertificateEntry("buddy-ca", certificate)
            }
            return TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).run {
                init(trusted)
                trustManagers.single() as X509TrustManager
            }
        }
    }
}

/** Owned by one WSS attempt. Closing the raw socket also interrupts SSH authentication. */
internal class BuddySsh(private val profile: BuddySshProfile) : AutoCloseable {
    private val lock = Any()
    private val raw = Socket(Proxy.NO_PROXY)
    private var closed = false
    private var session: Session? = null

    fun client(base: OkHttpClient): OkHttpClient {
        val tls = SSLContext.getInstance("TLS").apply { init(null, arrayOf(profile.trust), null) }
        return base.newBuilder()
            .proxy(Proxy.NO_PROXY)
            .connectionPool(ConnectionPool())
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(5, TimeUnit.SECONDS)
            .sslSocketFactory(tls.socketFactory, profile.trust)
            .socketFactory(object : javax.net.SocketFactory() {
                override fun createSocket(): Socket {
                    try {
                        open()
                        return object : Socket(Proxy.NO_PROXY) {
                            override fun connect(endpoint: SocketAddress, timeout: Int) {
                                val address = endpoint as? InetSocketAddress
                                if (address?.address?.hostAddress != BuddySshProfile.LOOPBACK ||
                                    address.port != BuddySshProfile.PORT) {
                                    throw IOException("Unexpected device transport target")
                                }
                                super.connect(endpoint, timeout)
                            }
                        }
                    } catch (failure: Exception) {
                        close()
                        throw SocketException("Device SSH connection failed").apply { initCause(failure) }
                    }
                }

                override fun createSocket(host: String, port: Int): Socket = unsupported()
                override fun createSocket(host: String, port: Int, local: InetAddress, localPort: Int): Socket = unsupported()
                override fun createSocket(host: InetAddress, port: Int): Socket = unsupported()
                override fun createSocket(host: InetAddress, port: Int, local: InetAddress, localPort: Int): Socket = unsupported()

                private fun unsupported(): Nothing = throw SocketException("Unbound socket required")
            })
            .build()
    }

    internal fun open() {
        val knownHost = if (profile.sshPort == 22) profile.host else "[${profile.host}]:${profile.sshPort}"
        val ssh = JSch().apply {
            setKnownHosts("$knownHost ecdsa-sha2-nistp256 ${profile.hostKey}\n".byteInputStream())
            addIdentity(BuddySshIdentity.load(), null)
        }.getSession(profile.user, profile.host, profile.sshPort)
        ssh.setConfig("StrictHostKeyChecking", "yes")
        ssh.setConfig("server_host_key", "ecdsa-sha2-nistp256")
        ssh.setConfig("PreferredAuthentications", "publickey")
        ssh.setConfig("PubkeyAcceptedAlgorithms", BuddySshIdentity.SIGNATURE)
        ssh.setConfig("enable_server_sig_algs", "no")
        ssh.setSocketFactory(object : SocketFactory {
            override fun createSocket(host: String, port: Int): Socket {
                raw.connect(InetSocketAddress(host, port), 5_000)
                return raw
            }

            override fun getInputStream(socket: Socket) = socket.getInputStream()
            override fun getOutputStream(socket: Socket) = socket.getOutputStream()
        })
        try {
            ssh.connect(5_000)
            synchronized(lock) {
                check(!closed)
                ssh.setPortForwardingL(BuddySshProfile.LOOPBACK, BuddySshProfile.PORT,
                    BuddySshProfile.LOOPBACK, BuddySshProfile.PORT)
                session = ssh
            }
        } catch (failure: Exception) {
            ssh.disconnect()
            throw failure
        }
    }

    override fun close() {
        val previous = synchronized(lock) {
            closed = true
            session.also { session = null }
        }
        runCatching { raw.close() }
        previous?.disconnect()
    }
}
