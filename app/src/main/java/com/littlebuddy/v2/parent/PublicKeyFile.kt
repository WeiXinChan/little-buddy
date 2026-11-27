package com.littlebuddy.v2.parent

import java.math.BigInteger
import java.nio.ByteBuffer
import java.nio.charset.StandardCharsets
import java.util.Base64
import java.util.concurrent.atomic.AtomicInteger

/** A released PUBLIC payload, not a Grant, PIN, key handle or reusable authorization. */
internal class PublicKeyFile(private val now: () -> Long) {
    private val until = now() + 120_000
    private val phase = AtomicInteger(0) // 0 awaiting final admit; 1 ready; 2 IO; 3 committed; 4 cancelled
    private var bytes: ByteArray? = null
    @Synchronized fun release(publicKey: String): Boolean {
        val data = encode(publicKey)
        if (now() >= until || !phase.compareAndSet(0, 1)) { data.fill(0); return false }
        bytes = data; return true
    }
    @Synchronized private fun take(): ByteArray? {
        if (!allowed() || !phase.compareAndSet(1, 2)) return null
        return bytes.also { bytes = null }
    }
    fun allowed(): Boolean = phase.get() != 4 && now() < until
    @Synchronized fun cancel() {
        while (true) {
            val p = phase.get()
            if (p == 3 || p == 4 || phase.compareAndSet(p, 4)) break
        }
        bytes?.fill(0); bytes = null
    }
    interface Destination {
        fun write(bytes: ByteArray)
        fun publish()
        /** Deletes only this operation's newly created object; throw if unconfirmed. */
        fun delete()
    }
    enum class Result { SAVED, CANCELLED, FAILED, CLEANUP_FAILED }
    /** No monitor spans provider IO. A cancellation racing publish deletes the new object.
     * A cancellation after the completed decision does not remove a completed public file. */
    fun save(create: () -> Destination): Result {
        val data = take() ?: run { cancel(); return Result.CANCELLED }
        var output: Destination? = null
        var result = Result.FAILED
        try {
            if (!allowed()) result = Result.CANCELLED
            else {
                output = create()
                if (!allowed()) result = Result.CANCELLED
                else {
                    output.write(data)
                    if (!allowed()) result = Result.CANCELLED
                    else {
                        output.publish()
                        result = if (allowed() && phase.compareAndSet(2, 3)) Result.SAVED else Result.CANCELLED
                    }
                }
            }
        } catch (_: Exception) { result = Result.FAILED }
        finally {
            data.fill(0)
            if (phase.get() != 3) {
                try { output?.delete() } catch (_: Exception) { result = Result.CLEANUP_FAILED }
                cancel()
            }
        }
        return result
    }
    companion object {
        const val NAME = "wali-v2-device.pub"
        /** Exactly the OpenSSH public tuple; no comments, private fields, tokens or extra lines. */
        fun encode(value: String): ByteArray {
            require(value.length in 32..2048 && value.matches(Regex("ssh-rsa [A-Za-z0-9+/]+={0,2}")))
            val text = value.substring(8)
            val raw = Base64.getDecoder().decode(text)
            require(Base64.getEncoder().encodeToString(raw) == text)
            val b = ByteBuffer.wrap(raw)
            fun field(): ByteArray {
                require(b.remaining() >= 4); val count = b.int
                require(count in 1..1024 && count <= b.remaining())
                return ByteArray(count).also(b::get)
            }
            require(field().contentEquals("ssh-rsa".toByteArray(StandardCharsets.US_ASCII)))
            val exponent = BigInteger(field()); val modulus = BigInteger(field())
            require(!b.hasRemaining() && exponent >= BigInteger.valueOf(3) && exponent.testBit(0) &&
                exponent.bitLength() <= 32 && modulus.signum() > 0 && modulus.testBit(0) && modulus.bitLength() in 2048..4096)
            return (value + "\n").toByteArray(StandardCharsets.US_ASCII)
        }
    }
}
