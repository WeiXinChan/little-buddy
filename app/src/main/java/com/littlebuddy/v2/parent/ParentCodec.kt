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
            val extended = record.speechRate != 100 || record.durationSeconds != 600 || record.connection != null
            it.writeInt(if (record.connection?.sshUser != null) 3 else if (extended) 2 else 1); it.writeInt(PinHasher.ITERATIONS)
            it.write(record.salt); it.write(record.hash)
            it.writeInt(record.failures); it.writeLong(record.cooldownMs); it.writeInt(record.volumeLimit)
            if (extended) {
                it.writeInt(record.speechRate); it.writeInt(record.durationSeconds)
                it.writeBoolean(record.connection != null)
                record.connection?.let { value -> it.writeUTF(value.address); it.writeUTF(value.credential); if (value.sshUser != null) it.writeUTF(value.sshUser) }
            }
        }
        return bytes.toByteArray()
    }
    fun decode(bytes: ByteArray): ParentRecord {
        check(bytes.size in 72..1024)
        return DataInputStream(ByteArrayInputStream(bytes)).use {
            val version = it.readInt()
            check(version in 1..3 && it.readInt() == PinHasher.ITERATIONS)
            val salt = ByteArray(16).also(it::readFully)
            val hash = ByteArray(32).also(it::readFully)
            val failures = it.readInt(); val cooldown = it.readLong(); val volume = it.readInt()
            val rate = if (version >= 2) it.readInt() else 100
            val duration = if (version >= 2) it.readInt() else 600
            val connection = if (version >= 2 && it.readBoolean()) ParentConnection(it.readUTF(), it.readUTF(), if (version == 3) it.readUTF() else null) else null
            check(it.available() == 0)
            ParentRecord(salt, hash, failures, cooldown, volume, rate, duration, connection).also(::validate)
        }
    }
    private fun validate(record: ParentRecord) {
        check(record.salt.size == 16 && record.hash.size == 32)
        check(record.failures in 0..1_000_000 && record.cooldownMs in 0..3_600_000)
        ParentPlaybackSettings(record.volumeLimit, record.speechRate, record.durationSeconds)
    }
}
