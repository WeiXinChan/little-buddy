package com.littlebuddy

import com.littlebuddy.voice.PcmStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.TimeUnit

/** One producer (WebSocket reader), one consumer (native audio worker). */
internal class CloudPcm(
    private val trace: (String, Long) -> Unit,
    capacity: Int = 4,
    bufferEntireSegment: Boolean = false,
) : PcmStream {
    private val chunks = ArrayBlockingQueue<ShortArray>(capacity)
    private val segment = if (bufferEntireSegment) SegmentBuffer() else null
    @Volatile private var sealed = false
    @Volatile override var aborted = false
        private set
    override val ended get() = sealed && (segment?.empty ?: chunks.isEmpty())
    private var position = 0

    fun push(bytes: ByteArray): Boolean {
        check(!sealed && !aborted && bytes.size in 8..6406 && bytes.size % 2 == 0)
        val packet = ByteBuffer.wrap(bytes)
        check(packet.get().toInt() == 1 && packet.get().toInt() == 2 && packet.int == position)
        val count = packet.remaining() / 2
        check(position + count <= MAX_SAMPLES)
        if (segment != null) {
            segment.append(packet.order(ByteOrder.LITTLE_ENDIAN), count)
            position += count
            return position == count
        }
        val samples = ShortArray(count)
        packet.order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(samples)
        check(chunks.offer(samples, 4, TimeUnit.SECONDS))
        if (aborted) {
            chunks.remove(samples)
            error("PCM stream cancelled")
        }
        position += count
        return position == count
    }

    fun seal(samples: Int) {
        check(!sealed && !aborted && samples > 0 && samples == position)
        sealed = true
    }

    fun abort() {
        aborted = true
        chunks.clear()
        segment?.clear()
    }

    override fun poll(): ShortArray? {
        if (aborted) return null
        return if (segment != null) segment.poll() else chunks.poll()
    }

    // Game segments can arrive while the previous AudioTrack still owns the slot.
    // Buffer by sample count so the socket reader can reach playback receipts.
    private class SegmentBuffer {
        private var data: ShortArray? = ShortArray(MAX_SAMPLES)
        private var read = 0
        private var written = 0
        val empty get() = synchronized(this) { read == written }

        @Synchronized
        fun append(packet: ByteBuffer, samples: Int) {
            packet.asShortBuffer().get(checkNotNull(data), written, samples)
            written += samples
        }

        @Synchronized
        fun poll(): ShortArray? {
            if (read == written) return null
            val end = minOf(read + 3200, written)
            return checkNotNull(data).copyOfRange(read, end).also { read = end }
        }

        @Synchronized
        fun clear() {
            data?.fill(0)
            data = null
            read = written
        }
    }

    private companion object {
        const val MAX_SAMPLES = 240_000
    }
    override fun playbackRequested(operation: Long) = trace("playback_requested", operation)
    override fun playbackHeadAdvanced(operation: Long) = trace("playback_head_first_advance", operation)
}
