package com.littlebuddy.v2

/** All coordinates count mono 24kHz PCM frames, never bytes or wall time. */
internal interface TrackPort {
    val head: Long
    fun write(pcm: ShortArray, offset: Int): Int
    fun setVolume(percent: Int): Boolean = false
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
    private data class Local(val ticket:Long,val pcm:ShortArray,val deadline:Long,
        val head:()->Unit,val finished:()->Unit,val cancelled:()->Unit,var offset:Int=0,var progressed:Boolean=false)
    private var local:Local?=null
    private var stopping=false
    val localActive get()=local!=null
    val hasPending get() = queue.isNotEmpty() || local!=null

    /** A distinct purpose in the SAME native slot; never a server Binding or ACK. Takes ownership of PCM. */
    fun clarify(ticket:Long,pcm:ShortArray,onHead:()->Unit,onFinished:()->Unit,onCancelled:()->Unit) {
        try {
            check(!stopping && !quarantined && binding==null && track==null && local==null)
            require(pcm.size in 240..144000) // mono24k, at most6s; no arbitrary path or duration
        } catch(error:Throwable){pcm.fill(0);throw error} // never stop another purpose on rejected acquisition
        try {
            local=Local(ticket,pcm,now()+10000,onHead,onFinished,onCancelled)
            track=factory(); written=0;head=0;started=false;progress=now()
        } catch(error:Throwable) {pcm.fill(0);stop();throw error}
    }
    private fun tickLocal(value:Local) {
        check(now()<value.deadline)
        val native=checkNotNull(track)
        val position=native.head
        check(now()<value.deadline && position>=head && position<=written)
        head=position
        if(position>0 && !value.progressed){value.progressed=true;reportOutput(true);value.head()}
        if(local!==value || track!==native)return // synchronous cancellation wins over this tick
        if(value.offset==value.pcm.size && position==value.pcm.size.toLong()) {
            local=null // revoke before fallible release or callback
            value.pcm.fill(0)
            val proof=stop()
            check(proof.stopped && proof.released)
            value.finished();return
        }
        if(value.offset<value.pcm.size) {
            val count=native.write(value.pcm,value.offset)
            check(count in 0..value.pcm.size-value.offset)
            value.offset+=count;written+=count
            if(count>0 && !started){native.play();started=true}
        }
        check(now()<value.deadline)
    }
    var binding: Binding? = null; private set
    var quarantined = false; private set
    var suspended = false; private set
    private var track: TrackPort? = null
    private val queue = ArrayDeque<AudioPacket>()
    private var offset = 0
    private var written = 0L
    private var head = 0L
    private var progress = 0L
    private var actualOutput:(Boolean)->Unit={}
    fun observeOutput(observer:(Boolean)->Unit){actualOutput=observer}
    private var audible=false
    private fun reportOutput(value:Boolean){if(audible!=value){audible=value;actualOutput(value)}}
    private var started = false
    private var reported = -1L

    fun bind(value: Binding) {
        check(!stopping && !quarantined && binding == null && track == null && local==null)
        reportOutput(false)
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
            local?.let { tickLocal(it);return }
            // Reject an expired owner tick before reading a late native head, writing
            // samples or acknowledging anything. The old deadline is authoritative.
            if (queue.isNotEmpty()) check(now() - progress < 60_000)
            val position = native.head
            if (queue.isNotEmpty()) check(now() - progress < 60_000)
            // A native counter reset/wrap or impossible head invalidates the stream.
            check(position >= head && position <= written)
            if(position>head && !suspended && queue.isNotEmpty())reportOutput(true)
            if (position > head) { head = position; progress = now() }
            val packet = queue.firstOrNull()
            if (packet != null && position != reported) {
                ack(PlaybackAck(packet.binding, packet.segment, position, position >= packet.end))
                reported = position
            }
            if (packet != null && offset == packet.pcm.size && position >= packet.end) {
                queue.removeFirst().pcm.fill(0); offset = 0; reported = -1
                if(queue.isEmpty())reportOutput(false)
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
        } catch (failure: Throwable) {
            stop()
            throw failure
        }
    }

    fun setVolume(percent: Int) {
        require(percent in 0..100)
        check(!quarantined)
        // This operation never play/resume/unmutes a native track.
        track?.let { check(it.setVolume(percent)) }
    }

    fun suspendOutput() { reportOutput(false); track?.pause(); suspended = true }
    fun resumeConfirmedNoise() { check(suspended); track?.play(); suspended = false }

    fun stop(): StopResult {
        if(stopping)return StopResult(false,false) // no reentrant acquisition during cleanup/notification
        stopping=true
        val retiredLocal=local
        local=null
        retiredLocal?.pcm?.fill(0)
        val previousBinding=binding
        binding=null
        val native=track
        track=null
        queue.forEach{it.pcm.fill(0)};queue.clear();offset=0;suspended=false
        try {
            var stopped=!quarantined
            var released=!quarantined
            if(native!=null) {
                stopped=true;released=true
                // No observer executes before all independent native cleanup attempts.
                for(action in listOf<()->Unit>(native::mute,native::pause,native::flush,native::stop)) {
                    try{action()}catch(_:Exception){stopped=false}
                }
                try{native.release()}catch(_:Exception){released=false}
                quarantined=quarantined || !stopped || !released
            }
            val result=StopResult(stopped,released)
            if(native!=null){releasedBinding=previousBinding;lastStop=result}
            try{reportOutput(false)}catch(_:Throwable){}
            try{retiredLocal?.cancelled?.invoke()}catch(_:Throwable){}
            return result
        } finally {stopping=false}
    }
}
