package com.littlebuddy.v2.parent

import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec

/** A device merely being unlocked is not owner proof. The default refuses; the local system
 * issuer requires a fresh per-use Keystore crypto authentication and exact signed operation.
 * Implementations must validate a fresh, single-use, device-bound challenge for the exact
 * operation, against a registered issuer, and reject replay, expiry and revoked bindings.
 * Neither Intent extras nor a caller's boolean assertion are evidence of ownership. */
internal interface OwnerProof {
    fun consume(challenge: OwnerChallenge): Boolean
}
internal enum class OwnerOperation { INITIALIZE_PIN, RESET_PIN, PROVISION_ENDPOINT }
internal class OwnerChallenge(val nonce: ByteArray, val deviceBinding: String,
                             val operation: OwnerOperation, val expiresAt: Long)
internal object UnconfiguredOwnerProof : OwnerProof {
    override fun consume(challenge: OwnerChallenge) = false
}

internal class ParentRecord(val salt: ByteArray, val hash: ByteArray,
                          val failures: Int = 0, val cooldownMs: Long = 0,
                          val volumeLimit: Int = 60, val speechRate: Int = 100,
                          val durationSeconds: Int = 600, val connection: ParentConnection? = null) {
    fun updated(failures: Int = this.failures, cooldownMs: Long = this.cooldownMs,
                volumeLimit: Int = this.volumeLimit, speechRate: Int = this.speechRate,
                durationSeconds: Int = this.durationSeconds, connection: ParentConnection? = this.connection) =
        ParentRecord(salt.copyOf(), hash.copyOf(), failures, cooldownMs, volumeLimit, speechRate, durationSeconds, connection)
    fun withPin(salt: ByteArray, hash: ByteArray) = ParentRecord(salt, hash, volumeLimit = volumeLimit,
        speechRate = speechRate, durationSeconds = durationSeconds, connection = connection)
}

/** Implementations atomically commit the entire authenticated record or throw.
 * null means a genuinely unused store; missing data with an existing key must throw. */
internal interface ParentStore {
    fun read(): ParentRecord?
    fun write(record: ParentRecord, authorized: () -> Boolean)
    /** Legacy/in-memory adapters invoke authorized only at their final assignment boundary. */
    fun commit(record: ParentRecord, transaction: ParentCommit) {
        write(record, transaction::claim)
        check(transaction.committed) { "parent store omitted final decision" }
    }
}

internal open class PinHasher {
    open fun derive(pin: CharArray, salt: ByteArray): ByteArray {
        val spec = PBEKeySpec(pin, salt, ITERATIONS, 256)
        return try { SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded }
        finally { spec.clearPassword() }
    }
    companion object { const val ITERATIONS = 600_000 }
}

/** State monitor protects memory only. Never hold it over KDF, proof, Keystore or disk IO.
 * A tryLock serializes ALL worker mutations (including reservations and their KDF); concurrent
 * callers reject rather than queue stale state. Lifecycle epoch invalidation uses neither lock.
 * ParentCommit.claim after staging is the final logical mutation decision; disk commit/readback
 * completes before record publication. Protected reads reject while a worker mutation is busy. */
internal class ParentDomain(private val store: ParentStore, private val now: () -> Long,
                            private val requireWorker: () -> Unit,
                            private val owner: OwnerProof = UnconfiguredOwnerProof,
                            private val binding: String,
                            private val hasher: PinHasher = PinHasher()) {
    internal class Grant internal constructor(internal val generation: Long, internal val pageEpoch: Long)
    enum class State { UNOWNED, LOCKED, AUTHORIZED, COOLDOWN, QUARANTINED }
    private val lock = Any()
    private val worker = java.util.concurrent.locks.ReentrantLock()
    private val epoch = ParentEpoch()
    private var record: ParentRecord? = null
    private var quarantined = false
    private var generation = 0L
    private var grant: Grant? = null
    private var deadline = 0L
    private var cooldownUntil = 0L
    private var challenge: OwnerChallenge? = null
    // Lifecycle witness only; never accepted as a fresh receipt or commit authorization.
    private var savingChallenge: OwnerChallenge? = null

    init {
        requireWorker()
        try {
            record = store.read()
            cooldownUntil = now() + (record?.cooldownMs ?: 0)
        } catch (_: Exception) { quarantined = true }
    }

    fun enterPage(): Long = epoch.revoke()
    /** HOME/onPause/focus/page invalidation performs only an atomic update, never waits for IO. */
    fun revoke() { epoch.revoke() }
    /** A departing child must not revoke an already mounted, later page. */
    fun revokePage(candidate: Grant) { epoch.revokeIf(candidate.pageEpoch) }
    fun invalidatePage(page: Long) { epoch.revokeIf(page) }
    fun isAuthorized(candidate: Grant): Boolean = synchronized(lock) {
        valid(candidate) // UI/prepare observation only; acceptProtected performs final admission.
    }
    /** Internal navigation retains the verified session and deadline, but replaces page capability.
     * No IO, no queued navigation. Post-CAS time witness prevents an expired transfer. */
    fun nextPage(candidate: Grant): Grant? = synchronized(lock) {
        if (worker.isLocked || !valid(candidate)) return null
        val limit = deadline
        val next = epoch.advance(candidate.pageEpoch) ?: return null
        if (now() >= limit) { epoch.revokeIf(next); grant = null; return null }
        generation++
        Grant(generation, next).also { grant = it }
    }
    /** Only the concrete, synchronous in-memory decision belongs here. Never IO or callbacks
     * to providers. The decision is published in this call, not a reusable Boolean permission.
     * Used by the feedback ParentAuthorizer at its final staged publication/admission point. */
    fun acceptProtected(candidate: Grant, decision: () -> Unit): Boolean {
        requireWorker()
        if (worker.isHeldByCurrentThread || !worker.tryLock()) return false
        try {
            val tx = transaction(candidate.pageEpoch, candidate.generation, { deadline }) { valid(candidate) }
            try { tx.claim() } catch (_: ParentCommitRejected) { return false }
            try { decision() } catch (failure: Exception) { revokePage(candidate); throw failure }
            return true
        } finally { worker.unlock() }
    }
    fun state(): State = synchronized(lock) {
        when {
            quarantined -> State.QUARANTINED
            record == null -> State.UNOWNED
            now() < cooldownUntil -> State.COOLDOWN
            valid(grant) -> State.AUTHORIZED
            else -> State.LOCKED
        }
    }
    private fun valid(candidate: Grant?): Boolean {
        if (now() >= deadline && grant != null) {
            val page = grant!!.pageEpoch
            if (page == epoch.current()) { epoch.revokeIf(page); challenge = null }
            grant = null
        }
        return !quarantined && candidate != null && candidate === grant &&
            candidate.generation == generation && candidate.pageEpoch == epoch.current() && now() < deadline
    }
    fun localAction(candidate: Grant): Boolean = synchronized(lock) {
        if (!valid(candidate)) false else { deadline = now() + IDLE_MS; true }
    }
    fun beginOwnerOperation(operation: OwnerOperation, page: Long): OwnerChallenge? {
        // Random generation may block; it also stays outside the memory monitor.
        if (worker.isLocked) return null
        val nonce = ByteArray(32).also(SecureRandom()::nextBytes)
        return synchronized(lock) {
            if (quarantined || page != epoch.current() || worker.isLocked) null
            else OwnerChallenge(nonce, binding, operation, now() + 60_000).also { challenge = it }
        }
    }
    private fun permitted(page: Long, ticket: Long, extra: () -> Boolean): Boolean =
        !quarantined && page == epoch.current() && ticket == generation && extra()
    private fun transaction(page: Long, ticket: Long, expiresAt: (() -> Long)? = null,
                            extra: () -> Boolean = { true }): ParentCommit {
        var cutoff: Long? = null
        return ParentCommit(
            { synchronized(lock) { permitted(page, ticket, extra) } },
            { synchronized(lock) {
                // Freeze the deadline from the same state as the final authorization/CAS.
                cutoff = expiresAt?.invoke()
                permitted(page, ticket, extra) && epoch.claim(page)
            } },
            {
                // elapsedRealtime is monotonic: postSample < cutoff proves CAS < cutoff.
                // Reject conservatively even if expiry happened just AFTER an in-time CAS.
                val limit = cutoff
                if (limit == null || now() < limit) true
                else { epoch.revokeIf(page); false }
            })
    }

    fun replacePin(pin: CharArray, proof: OwnerChallenge, page: Long): Boolean {
        try {
            requireWorker()
            if (!asciiPin(pin) || worker.isHeldByCurrentThread || !worker.tryLock()) {
                PinDiagnostic.event(PinDiagnostic.Stage.SAVE, PinDiagnostic.Reason.EARLY_REJECT); return false
            }
            try {
                val ticket = synchronized(lock) {
                    if (quarantined || page != epoch.current() || challenge !== proof ||
                        now() >= proof.expiresAt || proof.deviceBinding != binding ||
                        proof.operation != (if (record == null) OwnerOperation.INITIALIZE_PIN else OwnerOperation.RESET_PIN)) {
                        PinDiagnostic.observe(PinDiagnostic.Stage.SAVE) { if (now() >= proof.expiresAt) PinDiagnostic.Reason.EXPIRED else PinDiagnostic.Reason.CHALLENGE_REJECT }; return false
                    }
                    challenge = null; savingChallenge = proof; generation
                }
                if (!owner.consume(proof)) { PinDiagnostic.event(PinDiagnostic.Stage.CONSUME, PinDiagnostic.Reason.REJECTED); return false }
                PinDiagnostic.event(PinDiagnostic.Stage.CONSUME, PinDiagnostic.Reason.SUCCESS)
                val salt = ByteArray(16).also(SecureRandom()::nextBytes)
                PinDiagnostic.event(PinDiagnostic.Stage.DERIVE, PinDiagnostic.Reason.BEGIN)
                val hash = try { hasher.derive(pin, salt) }
                catch (error: Exception) { PinDiagnostic.error(PinDiagnostic.Stage.DERIVE, error); throw error }
                PinDiagnostic.event(PinDiagnostic.Stage.DERIVE, PinDiagnostic.Reason.SUCCESS)
                val next = synchronized(lock) { record?.withPin(salt, hash) ?: ParentRecord(salt, hash) }
                val committed = persist(next, transaction(page, ticket, { proof.expiresAt }) { now() < proof.expiresAt })
                if (committed) synchronized(lock) {
                    cooldownUntil = 0; generation++; grant = null; challenge = null
                    epoch.revokeIf(page)
                }
                PinDiagnostic.observe(PinDiagnostic.Stage.RESULT) { when (state()) {
                    State.UNOWNED -> PinDiagnostic.Reason.UNOWNED
                    State.LOCKED -> PinDiagnostic.Reason.LOCKED
                    State.AUTHORIZED -> PinDiagnostic.Reason.AUTHORIZED
                    State.COOLDOWN -> PinDiagnostic.Reason.COOLDOWN
                    State.QUARANTINED -> PinDiagnostic.Reason.QUARANTINED
                } }
                return committed
            } catch (error: Exception) { PinDiagnostic.error(PinDiagnostic.Stage.SAVE, error); throw error }
            finally {
                synchronized(lock) { if (savingChallenge === proof) savingChallenge = null }
                worker.unlock()
            }
        } finally { pin.fill('\u0000') }
    }

    /** Normal PIN change requires the existing verified session, unlike forgotten-PIN recovery.
     * New material is staged on the worker and the actual Grant is checked again at publication. */
    fun changePin(candidate: Grant, pin: CharArray): Boolean {
        try {
            requireWorker()
            if (!asciiPin(pin) || worker.isHeldByCurrentThread || !worker.tryLock()) return false
            try {
                val previous = synchronized(lock) { if (!valid(candidate)) return false; record!! }
                val salt = ByteArray(16).also(SecureRandom()::nextBytes)
                val hash = hasher.derive(pin, salt)
                val committed = persist(previous.withPin(salt, hash),
                    transaction(candidate.pageEpoch, candidate.generation, { deadline }) { valid(candidate) })
                if (committed) synchronized(lock) {
                    cooldownUntil = 0; generation++; grant = null; challenge = null
                    epoch.revokeIf(candidate.pageEpoch)
                }
                return committed
            } finally { worker.unlock() }
        } finally { pin.fill('\u0000') }
    }

    fun verify(pin: CharArray, page: Long): Grant? {
        try {
            requireWorker()
            if (!asciiPin(pin) || worker.isHeldByCurrentThread || !worker.tryLock()) return null
            try {
                val initial = synchronized(lock) {
                    val current = record ?: return null
                    if (quarantined || page != epoch.current() || now() < cooldownUntil) return null
                    generation++; grant = null; deadline = 0; challenge = null
                    Pair(generation, current)
                }
                val failures = (initial.second.failures + 1).coerceAtMost(1_000_000)
                val penalty = if (failures % 5 == 0) penalty(failures) else 0L
                // No KDF until the failure reservation is durably committed. A reservation
                // already committed survives HOME; cancellation before claim does not hash.
                if (!persist(initial.second.updated(failures, penalty), transaction(page, initial.first))) return null
                synchronized(lock) { cooldownUntil = now() + penalty }
                if (page != epoch.current()) return null
                val derived = hasher.derive(pin, initial.second.salt)
                val matches = try { MessageDigest.isEqual(derived, initial.second.hash) } finally { derived.fill(0) }
                if (!matches) return null
                val next = synchronized(lock) { record!!.updated(0, 0) }
                if (!persist(next, transaction(page, initial.first))) return null
                return synchronized(lock) {
                    // A committed counter reset does not resurrect permission after HOME.
                    cooldownUntil = 0
                    if (!permitted(page, initial.first) { true }) null
                    else {
                        deadline = now() + IDLE_MS
                        Grant(generation, page).also { grant = it }
                    }
                }
            } finally { worker.unlock() }
        } finally { pin.fill('\u0000') }
    }
    fun volumeLimit(candidate: Grant): Int? = synchronized(lock) {
        // Avoid exposing a stale memory record between decision and physical readback.
        if (!worker.isLocked && valid(candidate)) record?.volumeLimit else null
    }
    fun saveVolumeLimit(candidate: Grant, limit: Int): Boolean {
        requireWorker()
        if (worker.isHeldByCurrentThread || !worker.tryLock()) return false
        try {
            val next = synchronized(lock) {
                if (limit !in 0..100 || !valid(candidate)) return false
                record!!.updated(volumeLimit = limit)
            }
            val committed = persist(next, transaction(candidate.pageEpoch, candidate.generation, { deadline }) { valid(candidate) })
            if (committed) synchronized(lock) {
                if (valid(candidate)) deadline = now() + IDLE_MS
            }
            return committed
        } finally { worker.unlock() }
    }
    /** Worker-only execution snapshot. Recheck authenticated storage/key presence before a new child session. */
    fun childConfiguration(): ParentChildConfiguration? {
        requireWorker()
        if (worker.isHeldByCurrentThread || !worker.tryLock()) return null
        try {
            val expected = synchronized(lock) { if (quarantined) return null; record } ?: return null
            val durable = checkNotNull(store.read())
            val memory = ParentCodec.encode(expected); val disk = ParentCodec.encode(durable)
            try { check(MessageDigest.isEqual(memory, disk)) } finally { memory.fill(0); disk.fill(0) }
            return ParentChildConfiguration(ParentPlaybackSettings(expected.volumeLimit, expected.speechRate,
                expected.durationSeconds), expected.connection)
        } catch (_: Exception) {
            synchronized(lock) { quarantined = true }; revoke(); return null
        } finally { worker.unlock() }
    }
    fun settings(candidate: Grant): ParentPlaybackSettings? = synchronized(lock) {
        if (worker.isLocked || !valid(candidate)) null else record?.let {
            ParentPlaybackSettings(it.volumeLimit, it.speechRate, it.durationSeconds)
        }
    }
    /** Lifecycle evidence for a pending/consumed save, not permission to commit or reuse a receipt. */
    fun ownerSaveCurrent(proof: OwnerChallenge, page: Long): Boolean = synchronized(lock) {
        val current = !quarantined && page == epoch.current() && now() < proof.expiresAt &&
            (challenge === proof || savingChallenge === proof)
        if (!current) PinDiagnostic.observe(PinDiagnostic.Stage.PAGE) {
            if (now() >= proof.expiresAt) PinDiagnostic.Reason.EXPIRED else PinDiagnostic.Reason.CHALLENGE_REJECT
        }
        current
    }
    fun ownerChallengeCurrent(proof: OwnerChallenge, page: Long): Boolean = synchronized(lock) {
        val current = !quarantined && page == epoch.current() && challenge === proof && now() < proof.expiresAt
        if (!current) PinDiagnostic.observe(PinDiagnostic.Stage.PAGE) {
            if (now() >= proof.expiresAt) PinDiagnostic.Reason.EXPIRED else PinDiagnostic.Reason.CHALLENGE_REJECT
        }
        current
    }
    fun saveSettings(candidate: Grant, settings: ParentPlaybackSettings): Boolean {
        requireWorker()
        if (worker.isHeldByCurrentThread || !worker.tryLock()) return false
        try {
            val next = synchronized(lock) {
                if (!valid(candidate)) return false
                record!!.updated(volumeLimit = settings.volume, speechRate = settings.rate,
                    durationSeconds = settings.durationSeconds)
            }
            return persist(next, transaction(candidate.pageEpoch, candidate.generation, { deadline }) { valid(candidate) })
        } finally { worker.unlock() }
    }
    /** Import an already-issued endpoint credential after a separate fresh system operation. */
    fun provisionConnection(proof: OwnerChallenge, page: Long, value: ParentConnection): Boolean {
        requireWorker()
        if (worker.isHeldByCurrentThread || !worker.tryLock()) return false
        try {
            val ticket = synchronized(lock) {
                if (record == null || !ownerChallengeCurrent(proof, page) || proof.deviceBinding != binding ||
                    proof.operation != OwnerOperation.PROVISION_ENDPOINT) return false
                challenge = null; generation
            }
            if (!owner.consume(proof)) return false
            val next = synchronized(lock) { record!!.updated(connection = value) }
            val saved = persist(next, transaction(page, ticket, { proof.expiresAt }) { now() < proof.expiresAt })
            if (saved) synchronized(lock) { generation++; grant = null; epoch.revokeIf(page) }
            return saved
        } finally { worker.unlock() }
    }
    private fun persist(next: ParentRecord, transaction: ParentCommit): Boolean = try {
        PinDiagnostic.event(PinDiagnostic.Stage.COMMIT, PinDiagnostic.Reason.BEGIN)
        store.commit(next, transaction)
        check(transaction.committed) { "parent store omitted final decision" }
        synchronized(lock) { record = next }
        PinDiagnostic.event(PinDiagnostic.Stage.COMMIT, PinDiagnostic.Reason.SUCCESS)
        true
    } catch (_: ParentCommitRejected) { PinDiagnostic.event(PinDiagnostic.Stage.COMMIT, PinDiagnostic.Reason.REJECTED); false }
    catch (error: Exception) {
        PinDiagnostic.error(PinDiagnostic.Stage.COMMIT, error)
        synchronized(lock) { quarantined = true }
        revoke(); false
    }
    companion object {
        const val IDLE_MS = 120_000L
        private fun asciiPin(pin: CharArray) = pin.size == 6 && pin.all { it in '0'..'9' }
        private fun penalty(failures: Int) = minOf(3_600_000L, 60_000L shl minOf(6, failures / 5 - 1))
    }
}
