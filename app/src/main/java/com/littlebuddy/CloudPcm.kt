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
) : PcmStream {
    private val chunks = ArrayBlockingQueue<ShortArray>(capacity)
    @Volatile private var sealed = false
    @Volatile override var aborted = false
        private set
    override val ended get() = sealed && chunks.isEmpty()
    private var position = 0

    fun push(bytes: ByteArray): Boolean {
        check(!sealed && !aborted && bytes.size in 8..6406 && bytes.size % 2 == 0)
        val packet = ByteBuffer.wrap(bytes)
        check(packet.get().toInt() == 1 && packet.get().toInt() == 2 && packet.int == position)
        val count = packet.remaining() / 2
        check(position + count <= 240_000)
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
    }

    override fun poll(): ShortArray? = if (aborted) null else chunks.poll()
    override fun playbackRequested(operation: Long) = trace("playback_requested", operation)
    override fun playbackHeadAdvanced(operation: Long) = trace("playback_head_first_advance", operation)
}
