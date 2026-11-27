package com.littlebuddy.v2.parent

import javax.crypto.SecretKey

/** Android supplies Keystore handles, tests supply synthetic keys; neither caches a lost key. */
internal interface ParentKeyProvider {
    fun exists(): Boolean
    fun existing(): SecretKey?
    /** Must fail if the alias already exists. Never replaces an existing or invalid key. */
    fun create(): SecretKey
}

internal interface ParentRecordFile {
    /** null only for an absent record, including AtomicFile recovery semantics. */
    fun read(): ByteArray?
    fun commit(bytes: ByteArray, authorized: () -> Boolean)
    fun publish(bytes: ByteArray, transaction: ParentCommit) {
        commit(bytes, transaction::claim)
        check(transaction.committed) { "parent file omitted final decision" }
    }
}

/** Key creation is a one-shot transition after an empty record AND absent alias were observed.
 * Legacy PIN policy requires its issuer; explicit local-management policy migrates/initializes
 * without a PIN. Both retain the same authenticated atomic persistence boundary.
 * Every later write requires an existing usable key and proves continuity against ciphertext
 * from the successful open/commit. Any failure permanently quarantines this store instance. */
internal class SealedParentStore(private val file: ParentRecordFile,
                                 private val keys: ParentKeyProvider,
                                 private val aad: ByteArray) : ParentStore {
    private enum class Phase { UNOPENED, FRESH, EXISTING, QUARANTINED }
    private var phase = Phase.UNOPENED
    private var witness: ByteArray? = null

    override fun read(): ParentRecord? = guarded {
        check(phase != Phase.QUARANTINED)
        val bytes = file.read()
        if (bytes == null) {
            check(phase != Phase.EXISTING && !keys.exists()) { "parent record unavailable" }
            phase = Phase.FRESH
            null
        } else {
            val key = checkNotNull(keys.existing()) { "parent key unavailable" }
            val plain = ParentEnvelope.open(bytes, key, aad)
            val record = try { ParentCodec.decode(plain) } finally { plain.fill(0) }
            witness = bytes.copyOf(); phase = Phase.EXISTING
            record
        }
    }

    override fun write(record: ParentRecord, authorized: () -> Boolean) =
        commit(record, ParentCommit(authorized))

    override fun commit(record: ParentRecord, transaction: ParentCommit) = guarded {
        check(phase == Phase.FRESH || phase == Phase.EXISTING) { "parent store unavailable" }
        transaction.checkAllowed()
        val key = if (phase == Phase.FRESH) {
            // Consume creation eligibility BEFORE attempting key creation or disk IO.
            phase = Phase.EXISTING
            check(file.read() == null && !keys.exists()) { "parent store no longer fresh" }
            keys.create()
        } else {
            val existing = checkNotNull(keys.existing()) { "parent key unavailable" }
            val proof = ParentEnvelope.open(checkNotNull(witness), existing, aad)
            proof.fill(0)
            existing
        }
        val plain = ParentCodec.encode(record)
        val encrypted = try { ParentEnvelope.seal(plain, key, aad) } finally { plain.fill(0) }
        transaction.checkAllowed()
        file.publish(encrypted, transaction)
        check(transaction.committed) { "parent file omitted final decision" }
        check(file.read()?.contentEquals(encrypted) == true) { "parent commit unavailable" }
        witness = encrypted
    }

    private inline fun <T> guarded(action: () -> T): T = try { action() }
    catch (e: ParentCommitRejected) {
        // Existing prepared writes can safely abort. A newly created alias without a record
        // cannot be treated as fresh again, even if cancellation caused the failed first commit.
        if (phase == Phase.EXISTING && witness == null) {
            phase = Phase.QUARANTINED
            throw IllegalStateException("parent initialization interrupted", e)
        }
        throw e
    }
    catch (e: Exception) { phase = Phase.QUARANTINED; throw e }
}
