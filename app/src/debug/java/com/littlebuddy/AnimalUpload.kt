package com.littlebuddy

import okhttp3.WebSocket
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Audio worker writes frames. The activity authorizes and seals on its dispatcher. */
internal class AnimalUpload(val operation: Long, private val socket: WebSocket) {
    private val pending = ArrayDeque<ShortArray>()
    private var started = false
    private var ready = false
    private var closed = false
    private var position = 0

    @Synchronized
    fun frame(samples: ShortArray, count: Int): Boolean {
        if (closed) return true
        if (ready) return write(samples, count)
        if (pending.size >= if (started) 250 else 25) {
            if (started) return false
            pending.removeFirst().fill(0)
        }
        pending.addLast(samples.copyOf(count))
        return true
    }

    @Synchronized
    fun start(message: JSONObject): Boolean {
        check(!started && !closed)
        started = true
        return socket.send(message.toString())
    }

    @Synchronized
    fun ready(): Boolean {
        if (!started || ready || closed) return false
        ready = true
        while (pending.isNotEmpty()) {
            val frame = pending.removeFirst()
            val sent = write(frame, frame.size)
            frame.fill(0)
            if (!sent) return false
        }
        return true
    }

    @Synchronized
    fun end(): Boolean = ready && !closed && position > 0 &&
        socket.send(JSONObject().put("v", 1).put("type", "turn.end").put("samples", position).toString())

    @Synchronized
    fun close() {
        closed = true
        pending.forEach { it.fill(0) }
        pending.clear()
    }

    private fun write(samples: ShortArray, count: Int): Boolean {
        if (position + count > 320_000 || socket.queueSize() > 160_000) return false
        val packet = ByteBuffer.allocate(6 + 2 * count)
        packet.put(1).put(1).putInt(position).order(ByteOrder.LITTLE_ENDIAN)
        repeat(count) { packet.putShort(samples[it]) }
        if (!socket.send(packet.array().toByteString())) return false
        position += count
        return true
    }
}
