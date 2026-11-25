package com.littlebuddy.v2.transport

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
import java.security.MessageDigest
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

internal class V2SshIdentity private constructor(
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
        internal const val ALIAS = "buddy-ssh-device-v2"
        private const val ALGORITHM = "ssh-rsa"
        internal const val SIGNATURE = "rsa-sha2-256"

        @Synchronized
        fun load(create: Boolean = false): V2SshIdentity {
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
            return V2SshIdentity(entry.privateKey, entry.certificate.publicKey as RSAPublicKey)
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

internal class V2SshProfile(
    val host: String,
    val user: String,
    val hostKey: String,
    val trust: X509TrustManager,
    val sshPort: Int = 22,
) {
    init {
        require(host.split('.').size==4 && host.split('.').all { it.toIntOrNull() in 0..255 && it.toIntOrNull().toString()==it })
        require(user.matches(Regex("[a-z_][a-z0-9_-]{0,30}")) && user!="root" && user!="little-buddy-device")
        require(sshPort==22)
        require(java.util.Base64.getEncoder().withoutPadding().encodeToString(MessageDigest.getInstance("SHA-256")
            .digest(java.util.Base64.getDecoder().decode(hostKey)))=="Z9Ty3OFZtTBeTMIS9iRfGhOIRaTJ0eRzxaMSxeggliI")
    }
    companion object {
        const val LOOPBACK = "127.0.0.1"
        const val PORT = 19483
        val endpoint = "https://$LOOPBACK:$PORT/v2/voice".toHttpUrl()

        fun load(context: Context, user: String): V2SshProfile {
            require(user.matches(Regex("[a-z_][a-z0-9_-]{0,30}")) && user != "root" && user != "little-buddy-device")
            val properties = Properties().apply {
                context.assets.open("v2-transport/ssh.properties").use { load(it) }
            }
            val host = properties.getProperty("host")
            val hostKey = properties.getProperty("hostKey")
            val ca = context.assets.open("v2-transport/ca.pem").use { it.readBytes() }
            return V2SshProfile(host, user, hostKey, trustFor(ca))
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
internal enum class Target(val path: String) { VOICE("/v2/voice"), FEEDBACK("/v2/feedback") }
internal object V2Forwarding {
    fun mapped(address: SocketAddress, port: Int): InetSocketAddress {
        val requested=address as? InetSocketAddress
        if(requested?.address?.hostAddress!=V2SshProfile.LOOPBACK || requested.port!=V2SshProfile.PORT || port !in 1..65535)
            throw IOException("Unexpected device transport target")
        return InetSocketAddress(V2SshProfile.LOOPBACK,port)
    }
}
internal class V2Ssh(private val profile: V2SshProfile) : AutoCloseable {
    private val lock = Any()
    private val raw = Socket(Proxy.NO_PROXY)
    private var closed = false
    private var session: Session? = null
    private var localPort=0

    fun client(base: OkHttpClient, target: Target = Target.VOICE): OkHttpClient {
        val tls = SSLContext.getInstance("TLS").apply { init(null, arrayOf(profile.trust), null) }
        return base.newBuilder()
            .proxy(Proxy.NO_PROXY)
            .followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false)
            .addInterceptor { chain ->
                val url=chain.request().url
                if (url.scheme!="https" || url.host!=V2SshProfile.LOOPBACK || url.port!=V2SshProfile.PORT ||
                    url.encodedPath!=target.path || url.query!=null || url.fragment!=null ||
                    url.username.isNotEmpty() || url.password.isNotEmpty()) throw IOException("Unexpected V2 WSS target")
                chain.proceed(chain.request())
            }
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
                                val mapped=synchronized(lock) { check(!closed);V2Forwarding.mapped(endpoint,localPort) }
                                super.connect(mapped,timeout)
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
        synchronized(lock) { check(!closed) }
        val knownHost = if (profile.sshPort == 22) profile.host else "[${profile.host}]:${profile.sshPort}"
        val ssh = JSch().apply {
            setKnownHosts("$knownHost ecdsa-sha2-nistp256 ${profile.hostKey}\n".byteInputStream())
            addIdentity(V2SshIdentity.load(), null)
        }.getSession(profile.user, profile.host, profile.sshPort)
        ssh.setConfig("StrictHostKeyChecking", "yes")
        ssh.setConfig("server_host_key", "ecdsa-sha2-nistp256")
        ssh.setConfig("PreferredAuthentications", "publickey")
        ssh.setConfig("PubkeyAcceptedAlgorithms", V2SshIdentity.SIGNATURE)
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
                localPort=ssh.setPortForwardingL(V2SshProfile.LOOPBACK, 0,
                    V2SshProfile.LOOPBACK, V2SshProfile.PORT)
                check(localPort in 1..65535)
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
            session.also { session = null;localPort=0 }
        }
        runCatching { raw.close() }
        previous?.disconnect()
    }
}
