package com.littlebuddy.v2.parent

import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec

/** Trusted issuer integration is deliberately absent. A device unlock is not owner proof.
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
                          val volumeLimit: Int = 60) {
    fun updated(failures: Int = this.failures, cooldownMs: Long = this.cooldownMs,
                volumeLimit: Int = this.volumeLimit) =
        ParentRecord(salt.copyOf(), hash.copyOf(), failures, cooldownMs, volumeLimit)
}

/** Implementations atomically commit the entire authenticated record or throw.
 * null means a genuinely unused store; missing data with an existing key must throw. */
internal interface ParentStore {
    fun read(): ParentRecord?
    fun write(record: ParentRecord, authorized: () -> Boolean)
}

internal class PinHasher {
    fun derive(pin: CharArray, salt: ByteArray): ByteArray {
        val spec = PBEKeySpec(pin, salt, ITERATIONS, 256)
        return try { SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded }
        finally { spec.clearPassword() }
    }
    companion object { const val ITERATIONS = 600_000 }
}

/** One process-local domain per device. IO/KDF entry points require a serial worker.
 * Grants have reference identity, no Parcelable/Serializable or saved-state representation.
 * Lock serializes final authorization with atomic disk commit; lifecycle revocation linearizes
 * either before commit (reject) or after it (already committed). No deferred write queue. */
internal class ParentDomain(private val store: ParentStore, private val now: () -> Long,
                            private val requireWorker: () -> Unit,
                            private val owner: OwnerProof = UnconfiguredOwnerProof,
                            private val binding: String,
                            private val hasher: PinHasher = PinHasher()) {
    internal class Grant internal constructor(internal val generation: Long, internal val pageEpoch: Long)
    enum class State { UNOWNED, LOCKED, AUTHORIZED, COOLDOWN, QUARANTINED }
    private val lock = Any()
    private var record: ParentRecord? = null
    private var quarantined = false
    private var generation = 0L
    private var pageEpoch = 0L
    private var grant: Grant? = null
    private var deadline = 0L
    private var cooldownUntil = 0L
    private var verifying = false
    private var challenge: OwnerChallenge? = null

    init {
        requireWorker()
        try {
            record = store.read()
            // Conservatively restart the full recorded penalty on every process restart.
            // No wall clock is consulted. Killing/rebooting can only extend a penalty.
            cooldownUntil = now() + (record?.cooldownMs ?: 0)
        } catch (_: Exception) { quarantined = true }
    }

    fun enterPage(): Long = synchronized(lock) { revokeLocked(); pageEpoch }
    /** Call on HOME/onPause, focus loss, lock screen, page rebuild, cancel and exit. */
    fun revoke() = synchronized(lock) { revokeLocked() }
    private fun revokeLocked() {
        generation++; pageEpoch++; grant = null; deadline = 0; challenge = null
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
        if (now() >= deadline && grant != null) revokeLocked()
        return !quarantined && candidate != null && candidate === grant &&
            candidate.generation == generation && candidate.pageEpoch == pageEpoch && now() < deadline
    }
    /** Only a local valid parent action may call this, never network/audio/heartbeat events. */
    fun localAction(candidate: Grant): Boolean = synchronized(lock) {
        if (!valid(candidate)) false else { deadline = now() + IDLE_MS; true }
    }

    fun beginOwnerOperation(operation: OwnerOperation, epoch: Long): OwnerChallenge? = synchronized(lock) {
        if (quarantined || epoch != pageEpoch || verifying) return@synchronized null
        OwnerChallenge(ByteArray(32).also(SecureRandom()::nextBytes), binding, operation,
            now() + 60_000).also { challenge = it }
    }

    /** Synthetic OwnerProof implementations are test evidence only. Production always denies
     * until a reviewed issuer/provider is wired. Recovery never clears configuration/pairing. */
    fun replacePin(pin: CharArray, proof: OwnerChallenge, epoch: Long): Boolean {
        try {
            requireWorker()
            if (!asciiPin(pin)) return false
            val ticket = synchronized(lock) {
                if (quarantined || verifying || epoch != pageEpoch || challenge !== proof ||
                    now() >= proof.expiresAt || proof.deviceBinding != binding ||
                    proof.operation != (if (record == null) OwnerOperation.INITIALIZE_PIN else OwnerOperation.RESET_PIN)) return false
                challenge = null; verifying = true; generation
            }
            try {
                if (!owner.consume(proof)) return false
                val salt = ByteArray(16).also(SecureRandom()::nextBytes)
                val hash = hasher.derive(pin, salt)
                return synchronized(lock) {
                    if (quarantined || ticket != generation || epoch != pageEpoch || now() >= proof.expiresAt) false
                    else persist(ParentRecord(salt, hash, volumeLimit = record?.volumeLimit ?: 60)) {
                        ticket == generation && epoch == pageEpoch && now() < proof.expiresAt
                    }.also {
                        if (it) { cooldownUntil = 0; revokeLocked() }
                    }
                }
            } finally { synchronized(lock) { verifying = false } }
        } finally { pin.fill('\u0000') }
    }

    fun verify(pin: CharArray, epoch: Long): Grant? {
        try {
            requireWorker()
            if (!asciiPin(pin)) return null
            val reservation = synchronized(lock) {
                val current = record ?: return null
                if (quarantined || verifying || epoch != pageEpoch || now() < cooldownUntil) return null
                revokeGrantOnly()
                val failures = (current.failures + 1).coerceAtMost(1_000_000)
                val penalty = if (failures % 5 == 0) penalty(failures) else 0L
                // Reserve before expensive verification so crashes count as failures.
                if (!persist(current.updated(failures, penalty))) return null
                cooldownUntil = now() + penalty
                verifying = true
                Pair(generation, current)
            }
            var derived: ByteArray? = null
            try {
                derived = hasher.derive(pin, reservation.second.salt)
                val matches = MessageDigest.isEqual(derived, reservation.second.hash)
                return synchronized(lock) {
                    if (!matches || quarantined || generation != reservation.first || pageEpoch != epoch) null
                    else if (!persist(record!!.updated(0, 0)) { generation == reservation.first && pageEpoch == epoch }) null
                    else {
                        cooldownUntil = 0; deadline = now() + IDLE_MS
                        Grant(generation, pageEpoch).also { grant = it }
                    }
                }
            } finally { derived?.fill(0); synchronized(lock) { verifying = false } }
        } finally { pin.fill('\u0000') }
    }
    private fun revokeGrantOnly() { generation++; grant = null; deadline = 0; challenge = null }
    fun volumeLimit(candidate: Grant): Int? = synchronized(lock) {
        if (valid(candidate)) record?.volumeLimit else null
    }
    /** Invoke from the worker at completion time, including after asynchronous preparation. */
    fun saveVolumeLimit(candidate: Grant, limit: Int): Boolean {
        requireWorker()
        return synchronized(lock) {
            if (limit !in 0..100 || !valid(candidate)) false
            else persist(record!!.updated(volumeLimit = limit)) { valid(candidate) }.also {
                if (it) deadline = now() + IDLE_MS
            }
        }
    }
    private fun persist(next: ParentRecord, authorized: () -> Boolean = { true }): Boolean = try {
        store.write(next, authorized); record = next; true
    } catch (_: Exception) { quarantined = true; revokeLocked(); false }
    companion object {
        const val IDLE_MS = 120_000L
        private fun asciiPin(pin: CharArray) = pin.size == 6 && pin.all { it in '0'..'9' }
        private fun penalty(failures: Int) = minOf(3_600_000L, 60_000L shl minOf(6, failures / 5 - 1))
    }
}
