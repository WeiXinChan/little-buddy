package com.littlebuddy.v2.parent

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream

/** Fixed bounded format; unknown schema, truncation, trailing bytes and invalid values deny. */
internal object ParentCodec {
    fun encode(record: ParentRecord): ByteArray {
        validate(record)
        val bytes = ByteArrayOutputStream()
        DataOutputStream(bytes).use {
            it.writeInt(1); it.writeInt(PinHasher.ITERATIONS)
            it.write(record.salt); it.write(record.hash)
            it.writeInt(record.failures); it.writeLong(record.cooldownMs); it.writeInt(record.volumeLimit)
        }
        return bytes.toByteArray()
    }
    fun decode(bytes: ByteArray): ParentRecord {
        check(bytes.size == 72)
        return DataInputStream(ByteArrayInputStream(bytes)).use {
            check(it.readInt() == 1 && it.readInt() == PinHasher.ITERATIONS)
            val salt = ByteArray(16).also(it::readFully)
            val hash = ByteArray(32).also(it::readFully)
            ParentRecord(salt, hash, it.readInt(), it.readLong(), it.readInt()).also(::validate)
        }
    }
    private fun validate(record: ParentRecord) {
        check(record.salt.size == 16 && record.hash.size == 32)
        check(record.failures in 0..1_000_000 && record.cooldownMs in 0..3_600_000)
        check(record.volumeLimit in 0..100)
    }
}
