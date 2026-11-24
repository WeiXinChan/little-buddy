package com.littlebuddy.v2

/** All coordinates count mono 24kHz PCM frames, never bytes or wall time. */
internal interface TrackPort {
    val head: Long
    fun write(pcm: ShortArray, offset: Int): Int
    fun play()
    fun pause()
    fun mute()
    fun flush()
    fun stop()
    fun release()
}

internal data class Binding(val epoch: Long, val player: String, val stream: Int)
internal data class AudioPacket(val binding: Binding, val segment: String, val start: Long,
                               val end: Long, val pcm: ShortArray)
internal data class PlaybackAck(val binding: Binding, val segment: String, val head: Long, val completed: Boolean = false)
internal data class StopResult(val stopped: Boolean, val released: Boolean)

/** Production queue/pump; AndroidTrack supplies the actual playback head.
 * Owner is the audio Handler. Cancellation precedes upstream cancellation.
 */
internal class Playback(private val factory: () -> TrackPort, private val now: () -> Long,
                        private val ack: (PlaybackAck) -> Unit) {
    private var releasedBinding: Binding? = null
    private var lastStop: StopResult? = null
    fun nativeProof() = PlayerProof(binding, head, releasedBinding, lastStop)
    val hasPending get() = queue.isNotEmpty()
    var binding: Binding? = null; private set
    var quarantined = false; private set
    var suspended = false; private set
    private var track: TrackPort? = null
    private val queue = ArrayDeque<AudioPacket>()
    private var offset = 0
    private var written = 0L
    private var head = 0L
    private var progress = 0L
    private var started = false
    private var reported = -1L

    fun bind(value: Binding) {
        check(!quarantined && binding == null && track == null)
        val native = factory()
        track = native
        binding = value
        written = 0; head = 0; reported = -1; started = false; progress = now()
    }

    fun enqueue(packet: AudioPacket): Boolean {
        if (packet.binding != binding || quarantined) { packet.pcm.fill(0); return false }
        require(packet.segment.isNotEmpty() && packet.pcm.isNotEmpty() && packet.pcm.size <= 2400)
        require(packet.start == (queue.lastOrNull()?.end ?: written) &&
                packet.end == packet.start + packet.pcm.size)
        check(queue.sumOf { it.pcm.size } + packet.pcm.size <= 24000 && queue.size < 10)
        queue.addLast(packet)
        return true
    }

    fun tick() {
        val native = track ?: return
        try {
            // Reject an expired owner tick before reading a late native head, writing
            // samples or acknowledging anything. The old deadline is authoritative.
            if (queue.isNotEmpty()) check(now() - progress < 60_000)
            val position = native.head
            if (queue.isNotEmpty()) check(now() - progress < 60_000)
            // A native counter reset/wrap or impossible head invalidates the stream.
            check(position >= head && position <= written)
            if (position > head) { head = position; progress = now() }
            val packet = queue.firstOrNull()
            if (packet != null && position != reported) {
                ack(PlaybackAck(packet.binding, packet.segment, position, position >= packet.end))
                reported = position
            }
            if (packet != null && offset == packet.pcm.size && position >= packet.end) {
                queue.removeFirst().pcm.fill(0); offset = 0; reported = -1
            }
            if (!suspended) {
                val next = queue.firstOrNull()
                if (next != null && offset < next.pcm.size) {
                    val count = native.write(next.pcm, offset)
                    check(count in 0..(next.pcm.size - offset))
                    offset += count; written += count
                    if (count > 0 && !started) { native.play(); started = true }
                }
            }
            // Writes, duplicate ACKs, network pings and pauses never renew this clock.
            if (queue.isNotEmpty()) check(now() - progress < 60_000)
        } catch (failure: Exception) {
            stop()
            throw failure
        }
    }

    fun suspendOutput() { track?.pause(); suspended = true }
    fun resumeConfirmedNoise() { check(suspended); track?.play(); suspended = false }

    fun stop(): StopResult {
        // Revoke before any fallible native call. Late ACK/audio cannot bind again.
        val previousBinding = binding
        binding = null
        val native = track
        track = null
        queue.forEach { it.pcm.fill(0) }; queue.clear(); offset = 0
        suspended = false
        if (native == null) return StopResult(!quarantined, !quarantined)
        var stopped = true
        var released = true
        // Each step is attempted even if an earlier step throws.
        for (action in listOf<() -> Unit>(native::mute, native::pause, native::flush, native::stop)) {
            try { action() } catch (_: Exception) { stopped = false }
        }
        try { native.release() } catch (_: Exception) { released = false }
        quarantined = quarantined || !stopped || !released
        val result = StopResult(stopped, released)
        releasedBinding = previousBinding; lastStop = result
        return result
    }
}
