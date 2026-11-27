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
            val local = record.salt.isEmpty() && record.hash.isEmpty()
            val extended = local || record.speechRate != 100 || record.durationSeconds != 600 || record.connection != null
            it.writeInt(if (local) 4 else if (record.connection?.sshUser != null) 3 else if (extended) 2 else 1); it.writeInt(if (local) 0 else PinHasher.ITERATIONS)
            it.write(record.salt); it.write(record.hash)
            it.writeInt(record.failures); it.writeLong(record.cooldownMs); it.writeInt(record.volumeLimit)
            if (extended) {
                it.writeInt(record.speechRate); it.writeInt(record.durationSeconds)
                it.writeBoolean(record.connection != null)
                record.connection?.let { value -> it.writeUTF(value.address); it.writeUTF(value.credential); if (local) { it.writeBoolean(value.sshUser != null); value.sshUser?.let(it::writeUTF) } else if (value.sshUser != null) it.writeUTF(value.sshUser) }
            }
        }
        return bytes.toByteArray()
    }
    fun decode(bytes: ByteArray): ParentRecord {
        check(bytes.size in 33..1024)
        return DataInputStream(ByteArrayInputStream(bytes)).use {
            val version = it.readInt()
            check(version in 1..4 && it.readInt() == if (version == 4) 0 else PinHasher.ITERATIONS)
            val salt = ByteArray(if (version == 4) 0 else 16).also(it::readFully)
            val hash = ByteArray(if (version == 4) 0 else 32).also(it::readFully)
            val failures = it.readInt(); val cooldown = it.readLong(); val volume = it.readInt()
            val rate = if (version >= 2) it.readInt() else 100
            val duration = if (version >= 2) it.readInt() else 600
            val connection = if (version >= 2 && it.readBoolean()) ParentConnection(it.readUTF(), it.readUTF(), if (version == 3 || (version == 4 && it.readBoolean())) it.readUTF() else null) else null
            check(it.available() == 0)
            ParentRecord(salt, hash, failures, cooldown, volume, rate, duration, connection).also(::validate)
        }
    }
    private fun validate(record: ParentRecord) {
        check((record.salt.size == 16 && record.hash.size == 32) ||
            (record.salt.isEmpty() && record.hash.isEmpty() && record.failures == 0 && record.cooldownMs == 0L))
        check(record.failures in 0..1_000_000 && record.cooldownMs in 0..3_600_000)
        ParentPlaybackSettings(record.volumeLimit, record.speechRate, record.durationSeconds)
    }
}
