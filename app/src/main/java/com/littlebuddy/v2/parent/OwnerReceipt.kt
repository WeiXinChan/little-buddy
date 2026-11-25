package com.littlebuddy.v2.parent

import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.security.MessageDigest
import java.security.PublicKey
import java.security.Signature
import java.util.concurrent.ConcurrentHashMap

/** A signed one-shot operation, not a successful-unlock boolean or installation identifier. */
internal class OwnerReceipt(private val publicKey: PublicKey, private val binding: String,
    private val now: () -> Long) : OwnerProof {
    private class Receipt(val challenge: OwnerChallenge, val message: ByteArray, val signature: ByteArray)
    private val receipts = ConcurrentHashMap<OwnerChallenge, Receipt>()
    private val reservation = Any()
    private fun wipe(value: Receipt) { value.message.fill(0); value.signature.fill(0) }
    fun approve(challenge: OwnerChallenge, sign: (ByteArray) -> ByteArray): Boolean {
        if (challenge.deviceBinding != binding || now() >= challenge.expiresAt) return false
        val message = message(challenge)
        val bytes = sign(message)
        val valid = Signature.getInstance("SHA256withECDSA").run {
            initVerify(publicKey); update(message); verify(bytes)
        }
        if (!valid || now() >= challenge.expiresAt) { message.fill(0); bytes.fill(0); return false }
        for ((key, value) in receipts) if (now() >= key.expiresAt && receipts.remove(key, value)) wipe(value)
        val value = Receipt(challenge, message, bytes)
        return synchronized(reservation) {
            if (receipts.size >= 4 || receipts.putIfAbsent(challenge, value) != null) { wipe(value); false }
            else true
        }
    }
    fun discard(challenge: OwnerChallenge) { receipts.remove(challenge)?.let(::wipe) }
    override fun consume(challenge: OwnerChallenge): Boolean {
        val value = receipts.remove(challenge) ?: return false
        return try {
            val current = message(challenge)
            try { challenge.deviceBinding == binding && now() < challenge.expiresAt &&
                MessageDigest.isEqual(value.message, current) && Signature.getInstance("SHA256withECDSA").run {
                    initVerify(publicKey); update(current); verify(value.signature)
                }
            } finally { current.fill(0) }
        } finally { value.message.fill(0); value.signature.fill(0) }
    }
    companion object {
        fun message(challenge: OwnerChallenge): ByteArray = ByteArrayOutputStream().also { out ->
            DataOutputStream(out).use {
                it.writeUTF("little-buddy:local-system-owner:v1"); it.writeUTF(challenge.deviceBinding)
                it.writeUTF(challenge.operation.name); it.writeLong(challenge.expiresAt)
                it.writeInt(challenge.nonce.size); it.write(challenge.nonce)
            }
        }.toByteArray()
    }
}
