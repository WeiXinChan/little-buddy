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
    private val sealed = SealedParentStore(object : ParentRecordFile {
        override fun read(): ByteArray? = try { file.readFully() }
        catch (_: java.io.FileNotFoundException) { null }
        override fun commit(bytes: ByteArray, authorized: () -> Boolean) {
            check(authorized()) { "parent authorization expired" }
            val output = file.startWrite()
            try {
                output.write(bytes)
                check(authorized()) { "parent authorization expired" }
                file.finishWrite(output)
            } catch (e: Exception) { file.failWrite(output); throw e }
        }
    }, AndroidParentKeys(), aad)
    override fun read(): ParentRecord? {
        worker()
        return sealed.read()
    }
    override fun write(record: ParentRecord, authorized: () -> Boolean) {
        worker()
        sealed.write(record, authorized)
    }
    companion object {
        fun worker() { check(Looper.myLooper() != Looper.getMainLooper()) { "parent worker required" } }
    }
}

/** Creation is reachable only through SealedParentStore's one-shot fresh transition. */
private class AndroidParentKeys : ParentKeyProvider {
    private fun store() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    override fun exists() = store().containsAlias(ALIAS)
    override fun existing() = store().getKey(ALIAS, null) as SecretKey?
    override fun create(): SecretKey {
        check(!exists()) { "parent alias already exists" }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
            init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256).build())
            generateKey()
        }
    }
    companion object { private const val ALIAS = "little-buddy-v2-parent-v1" }
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
