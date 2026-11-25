package com.littlebuddy.v2.parent

import android.content.Context
import android.os.Looper
import android.os.SystemClock
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import java.security.KeyStore
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

/** Entire record (including limits and retry reservations) is authenticated, in noBackup.
 * Distinct from V1 aliases/files. A lost key or missing record with an existing key fails closed.
 * Root/data rollback and uninstall+keystore deletion are outside this local threat boundary. */
internal class AndroidParentStore(context: Context, binding: String) : ParentStore {
    private val file = AtomicFile(context.noBackupFilesDir.resolve("v2-parent-v1"))
    private val aad = "little-buddy:v2:parent:1:$binding".toByteArray(Charsets.UTF_8)
    init { require(binding.isNotBlank() && binding.length <= 512) }
    private fun keyStore() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    private fun key(create: Boolean): SecretKey {
        val existing = keyStore().getKey(ALIAS, null)
        if (existing != null) return existing as SecretKey
        check(create) { "parent key unavailable" }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
            init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256).build())
            generateKey()
        }
    }
    override fun read(): ParentRecord? {
        worker()
        // AtomicFile may recover a .bak after interrupted commit; never inspect base alone.
        val bytes = try { file.readFully() } catch (e: java.io.FileNotFoundException) {
            check(!keyStore().containsAlias(ALIAS)) { "parent record unavailable" }
            return null
        }
        val plain = ParentEnvelope.open(bytes, key(false), aad)
        return try { ParentCodec.decode(plain) } finally { plain.fill(0) }
    }
    override fun write(record: ParentRecord, authorized: () -> Boolean) {
        worker()
        val plain = ParentCodec.encode(record)
        val encrypted = try {
            ParentEnvelope.seal(plain, key(true), aad)
        } finally { plain.fill(0) }
        check(authorized()) { "parent authorization expired" }
        val output = file.startWrite()
        try {
            output.write(encrypted)
            // Recheck immediately before publication, including time spent in encryption/IO.
            check(authorized()) { "parent authorization expired" }
            file.finishWrite(output)
        } catch (e: Exception) { file.failWrite(output); throw e }
        // Detect reported/partial storage faults before granting any further capability.
        check(file.readFully().contentEquals(encrypted)) { "parent commit unavailable" }
    }
    companion object {
        private const val ALIAS = "little-buddy-v2-parent-v1"
        fun worker() { check(Looper.myLooper() != Looper.getMainLooper()) { "parent worker required" } }
    }
}

/** Factory owns one live authority per process. UI/provider wiring remains intentionally absent. */
internal object AndroidParentDomain {
    enum class Capability { UNCONFIGURED }
    // Explicit integration status; PIN possession never implies endpoint issuance rights.
    val firstOwnership = Capability.UNCONFIGURED
    val systemRecovery = Capability.UNCONFIGURED
    val endpointIssuance = Capability.UNCONFIGURED
    private var domain: ParentDomain? = null
    private var binding: String? = null
    @Synchronized fun open(context: Context, deviceBinding: String): ParentDomain {
        AndroidParentStore.worker()
        check(binding == null || binding == deviceBinding)
        return domain ?: ParentDomain(AndroidParentStore(context.applicationContext, deviceBinding),
            SystemClock::elapsedRealtime, AndroidParentStore::worker, binding = deviceBinding).also {
            binding = deviceBinding; domain = it
        }
    }
}
