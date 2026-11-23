package com.littlebuddy

import okhttp3.WebSocket
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** The recorder appends samples. The activity drains small batches on its dispatcher. */
internal class AnimalUpload(
    val operation: Long,
    private var socket: WebSocket?,
    val synthetic: Boolean,
) {
    enum class Drain { IDLE, MORE, BLOCKED, ENDED, FAILED }

    private val deferred = socket == null
    private val pending = ShortArray(CAPACITY)
    private var head = 0
    private var size = 0
    private var started = false
    private var ready = false
    private var closed = false
    private var ended = false
    private var position = 0

    @Synchronized
    fun frame(samples: ShortArray, count: Int): Boolean {
        if (closed || ended) return true
        require(count in 1..minOf(PACKET_SAMPLES, samples.size))
        if (!deferred && !started) {
            val discard = (size + count - 8000).coerceAtLeast(0)
            remove(discard)
        }
        if (size + count > CAPACITY || position + size + count > 320_000) return false
        for (i in 0 until count) pending[(head + size + i) % CAPACITY] = samples[i]
        size += count
        return true
    }

    @Synchronized
    fun start(message: JSONObject, connection: WebSocket? = socket): Boolean {
        check(!started && !closed)
        socket = checkNotNull(connection)
        started = true
        return connection.send(message.toString())
    }

    @Synchronized
    fun ready(): Boolean {
        if (!started || ready || closed) return false
        ready = true
        return true
    }

    @Synchronized
    fun drain(sealed: Boolean): Drain {
        if (!ready || closed || ended) return Drain.IDLE
        val connection = checkNotNull(socket)
        repeat(16) {
            if (size < PACKET_SAMPLES && !sealed) return Drain.IDLE
            if (size == 0) {
                if (position == 0) return Drain.FAILED
                val end = JSONObject().put("v", 1).put("type", "turn.end").put("samples", position).toString()
                if (connection.queueSize() + end.length > WIRE_BUDGET) return Drain.BLOCKED
                ended = true
                return if (connection.send(end)) Drain.ENDED else Drain.FAILED
            }
            val count = minOf(size, PACKET_SAMPLES)
            val bytes = HEADER_BYTES + count * Short.SIZE_BYTES
            if (connection.queueSize() + bytes > WIRE_BUDGET) return Drain.BLOCKED
            val packet = ByteBuffer.allocate(bytes)
            packet.put(1).put(1).putInt(position).order(ByteOrder.LITTLE_ENDIAN)
            repeat(count) { packet.putShort(pending[(head + it) % CAPACITY]) }
            if (!connection.send(packet.array().toByteString())) return Drain.FAILED
            position += count
            remove(count)
        }
        return Drain.MORE
    }

    @Synchronized
    fun close() {
        closed = true
        remove(size)
    }

    private fun remove(count: Int) {
        repeat(count) { pending[(head + it) % CAPACITY] = 0 }
        head = (head + count) % CAPACITY
        size -= count
    }

    companion object {
        private const val PACKET_SAMPLES = 320
        private const val HEADER_BYTES = 6
        private const val CAPACITY = 80_000
        internal const val WIRE_BUDGET = CAPACITY / PACKET_SAMPLES * (HEADER_BYTES + PACKET_SAMPLES * 2)
    }
}
