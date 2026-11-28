package com.littlebuddy.v2.feedback

import java.io.*
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import javax.crypto.Cipher
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Real file port with atomic replacement and fsync; injected implementations enable disk fault tests. */
interface VaultFiles {
    fun read(name: String): ByteArray?
    fun replace(name: String, bytes: ByteArray)
    fun remove(name: String)
}
class PrivateVaultFiles(private val directory: File) : VaultFiles {
    private val names = setOf("materials", "ledger", "staging")
    init { require(directory.isDirectory || directory.mkdirs()) }
    private fun file(name: String): File {
        require(name in names)
        require(!Files.isSymbolicLink(directory.toPath()))
        return File(directory, name).also { require(!Files.isSymbolicLink(it.toPath())) }
    }
    override fun read(name: String): ByteArray? = file(name).let {
        if (!it.exists()) null else {
            require(it.length() <= 2 * 1024 * 1024)
            it.readBytes()
        }
    }
    override fun replace(name: String, bytes: ByteArray) {
        val target = file(name)
        val temp = File(directory, "$name.new")
        require(!Files.isSymbolicLink(temp.toPath()))
        try {
            FileOutputStream(temp).use { it.write(bytes); it.fd.sync() }
            Files.move(temp.toPath(), target.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
            java.nio.channels.FileChannel.open(directory.toPath(), java.nio.file.StandardOpenOption.READ).use { it.force(true) }
        } finally { Files.deleteIfExists(temp.toPath()) }
    }
    override fun remove(name: String) { Files.deleteIfExists(file(name).toPath()) }
}

/** Both blobs are authenticated; missing/mismatched ledger quarantines, never rebuilds from a snapshot.
 * The directory must be private/noBackup. Restoring BOTH files is unsupported: call quarantineRestore().
 */
class FeedbackVault(private val files: VaultFiles, private val key: SecretKey) {
    private var quarantined = false
    private fun crypt(input: ByteArray, encrypt: Boolean): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        require(encrypt || input.size >= 28)
        if (encrypt) {
            // AndroidKeyStore's randomized-encryption policy forbids caller-supplied IVs.
            cipher.init(Cipher.ENCRYPT_MODE, key)
        } else {
            // Keep the v1 on-disk layout: 12-byte IV followed by ciphertext + 128-bit tag.
            cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, input.copyOfRange(0, 12)))
        }
        val nonce = cipher.iv
        require(nonce.size == 12)
        cipher.updateAAD("little-buddy-m09-v1".toByteArray())
        return if (encrypt) nonce + cipher.doFinal(input) else cipher.doFinal(input, 12, input.size - 12)
    }
    /** Staging contains only ephemeral-key ciphertext. No durable material can be recovered from it.
     * A committed object is minted INSIDE the final authorization callback, never from a boolean.
     */
    internal inner class Staged(private val bytes: ByteArray) {
        private var decided = false
        fun decide(): Committed {
            check(!decided); decided = true
            return Committed(bytes)
        }
        fun discard() {
            if (!decided) bytes.fill(0)
            try { files.remove("staging") } catch (_: Exception) {
                quarantined = true; throw FeedbackFailure(Failure.STORAGE)
            }
        }
    }
    internal inner class Committed(private val bytes: ByteArray) {
        private var used = false
        fun persist() {
            check(!used); used = true
            try { save(bytes) } finally { bytes.fill(0) }
        }
    }
    @Synchronized internal fun stage(bytes: ByteArray): Staged {
        if (quarantined) throw FeedbackFailure(Failure.QUARANTINED)
        try {
            require(bytes.size <= 2 * 1024 * 1024 - 128)
            val generator = javax.crypto.KeyGenerator.getInstance("AES").apply { init(256) }
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, generator.generateKey())
            // Key is intentionally never serialized. Restart discards rather than recovers staging.
            files.replace("staging", cipher.iv + cipher.doFinal(bytes))
            return Staged(bytes)
        } catch (_: Exception) { bytes.fill(0); throw FeedbackFailure(Failure.STORAGE) }
    }
    @Synchronized fun quarantineRestore() { quarantined = true }
    @Synchronized internal fun load(): ByteArray? {
        if (quarantined) throw FeedbackFailure(Failure.QUARANTINED)
        try {
            files.remove("staging") // ephemeral-key work cannot be resumed after process loss
            val data = files.read("materials")
            val ledger = files.read("ledger")
            if (data == null && ledger == null) return null
            require(data != null && ledger != null)
            val expected = crypt(ledger, false).toString(Charsets.US_ASCII)
            require(expected == digest(data))
            return crypt(data, false)
        } catch (_: Exception) {
            quarantined = true
            throw FeedbackFailure(Failure.QUARANTINED)
        }
    }
    @Synchronized internal fun save(bytes: ByteArray) {
        if (quarantined) throw FeedbackFailure(Failure.QUARANTINED)
        try {
            require(bytes.size <= 2 * 1024 * 1024 - 128)
            val encrypted = crypt(bytes, true)
            // Ledger first: interrupted publication fails closed, including deletion failure.
            files.replace("ledger", crypt(digest(encrypted).toByteArray(Charsets.US_ASCII), true))
            files.replace("materials", encrypted)
        } catch (_: Exception) {
            quarantined = true
            throw FeedbackFailure(Failure.STORAGE)
        }
    }
}
