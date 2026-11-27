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
internal class AndroidParentStore(context: Context, binding: String, private val isolated: Boolean = false) : ParentStore {
    private val file = AtomicFile(context.noBackupFilesDir.resolve(if(isolated) LOCAL_FILE else "v2-parent-v1"))
    private val aad = (if(isolated) LOCAL_AAD else "little-buddy:v2:parent:1:$binding").toByteArray(Charsets.UTF_8)
    init { require(binding.isNotBlank() && binding.length <= 512) }
    private val sealed = SealedParentStore(object : ParentRecordFile {
        override fun read(): ByteArray? = try { file.readFully() }
        catch (_: java.io.FileNotFoundException) { null }
        override fun commit(bytes: ByteArray, authorized: () -> Boolean) {
            publish(bytes, ParentCommit(authorized))
        }
        override fun publish(bytes: ByteArray, transaction: ParentCommit) {
            transaction.checkAllowed()
            val output = file.startWrite()
            try {
                output.write(bytes)
                output.flush()
                output.fd.sync()
                // All prepared bytes are synced BEFORE the final atomic epoch/commit race.
                // finishWrite physically publishes an already-decided transaction; it may
                // still block/fail, but lifecycle invalidation never takes this worker's lock.
                transaction.claim()
                file.finishWrite(output)
            } catch (e: Exception) { file.failWrite(output); throw e }
        }
    }, AndroidParentKeys(if(isolated) LOCAL_ALIAS else "little-buddy-v2-parent-v1"), aad)
    override fun read(): ParentRecord? {
        worker()
        return ConfigurationDiagnostic.step(ConfigurationDiagnostic.Stage.STORE_READ) { sealed.read() }
    }
    override fun write(record: ParentRecord, authorized: () -> Boolean) {
        worker()
        sealed.write(record, authorized)
    }
    override fun commit(record: ParentRecord, transaction: ParentCommit) {
        worker()
        ConfigurationDiagnostic.observe(ConfigurationDiagnostic.Stage.STORE_COMMIT) { sealed.commit(record, transaction) }
    }
    companion object {
        const val LOCAL_FILE="v2-parent-local-v1"
        const val LOCAL_ALIAS="little-buddy-v2-parent-local-v1"
        const val LOCAL_AAD="little-buddy:v2:parent-local:1"
        fun hasIsolatedDomain(context:Context):Boolean {
            worker()
            return listOf(LOCAL_FILE,"$LOCAL_FILE.bak","$LOCAL_FILE.new").any { context.noBackupFilesDir.resolve(it).exists() } ||
                KeyStore.getInstance("AndroidKeyStore").apply{load(null)}.containsAlias(LOCAL_ALIAS)
        }
        fun hasExistingDomain(context: Context): Boolean {
            worker()
            return listOf("v2-parent-v1", "v2-parent-v1.bak", "v2-parent-v1.new").any { context.noBackupFilesDir.resolve(it).exists() } ||
                KeyStore.getInstance("AndroidKeyStore").apply { load(null) }.containsAlias("little-buddy-v2-parent-v1")
        }
        fun worker() { check(Looper.myLooper() != Looper.getMainLooper()) { "parent worker required" } }
    }
}

/** Creation is reachable only through SealedParentStore's one-shot fresh transition. */
private class AndroidParentKeys(private val alias:String) : ParentKeyProvider {
    private fun store() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    override fun exists() = ConfigurationDiagnostic.step(ConfigurationDiagnostic.Stage.KEY_PRESENCE) { store().containsAlias(alias) }.also {
        ConfigurationDiagnostic.event(ConfigurationDiagnostic.Stage.KEY_PRESENCE, if(it) ConfigurationDiagnostic.Reason.PRESENT else ConfigurationDiagnostic.Reason.ABSENT)
    }
    override fun existing() = ConfigurationDiagnostic.step(ConfigurationDiagnostic.Stage.KEY_LOAD) { store().getKey(alias, null) as SecretKey? }.also {
        ConfigurationDiagnostic.event(ConfigurationDiagnostic.Stage.KEY_LOAD, if(it!=null) ConfigurationDiagnostic.Reason.PRESENT else ConfigurationDiagnostic.Reason.ABSENT)
    }
    override fun create(): SecretKey {
        check(!exists()) { "parent alias already exists" }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256).build())
            generateKey()
        }
    }
}

/** One live domain per process/binding. Local management does not assert remote identity. */
internal object AndroidParentDomain {
    enum class Capability { APP_LOCAL_MANAGEMENT, EXTERNAL_ISSUER_REQUIRED }
    // Explicit integration status; PIN possession never implies endpoint issuance rights.
    val firstOwnership = Capability.APP_LOCAL_MANAGEMENT
    val systemRecovery = Capability.APP_LOCAL_MANAGEMENT
    val endpointIssuance = Capability.EXTERNAL_ISSUER_REQUIRED
    private var domain: ParentDomain? = null
    private var binding: String? = null
    @Synchronized fun open(context: Context, deviceBinding: String, owner: OwnerProof = UnconfiguredOwnerProof): ParentDomain {
        AndroidParentStore.worker()
        check(binding == null || binding == deviceBinding)
        return domain ?: ParentDomain(AndroidParentStore(context.applicationContext, deviceBinding),
            SystemClock::elapsedRealtime, AndroidParentStore::worker, owner, binding = deviceBinding, localManagement = true).also {
            binding = deviceBinding; domain = it
        }
    }
}

/** Independent local namespace. Never opens the legacy ciphertext or reuses its AES alias. */
internal object AndroidIsolatedParentDomain {
    private var domain:ParentDomain?=null
    @Synchronized fun open(context:Context):ParentDomain {
        AndroidParentStore.worker()
        return domain?:ParentDomain(AndroidParentStore(context.applicationContext,"isolated-local",true),
            SystemClock::elapsedRealtime,AndroidParentStore::worker,binding="isolated-local",localManagement=true)
            .also{domain=it}
    }
}
