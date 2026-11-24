package com.littlebuddy.v2

/** UI publishes immediately; queued owner work must validate the exact ticket. */
internal class LifecycleGate {
    data class State(val generation: Long=0, val resumed: Boolean=false, val focus: Boolean=false, val destroyed: Boolean=false)
    @Volatile var state=State(); private set
    @Synchronized fun resume(): Long { if(state.resumed)return state.generation; state=state.copy(generation=state.generation+1,resumed=true); return state.generation }
    @Synchronized fun focus(value: Boolean): Long { if(state.focus==value)return state.generation; state=state.copy(generation=state.generation+1,focus=value); return state.generation }
    @Synchronized fun pause(): Long { state=state.copy(generation=state.generation+1,resumed=false); return state.generation }
    @Synchronized fun destroy(): Long { state=state.copy(generation=state.generation+1,resumed=false,focus=false,destroyed=true); return state.generation }
    fun allows(ticket: Long): Boolean { val s=state; return s.generation==ticket && s.resumed && s.focus && !s.destroyed }
}

/** Fixed names/numeric state only; bounded, monotonic evidence, never conversation. */
internal class StopTimeline(private val now: ()->Long) {
    data class Event(val ms: Long,val event: String,val generation: Long,val session: Int?,val frames: Long,val recording: Boolean,val stopped: Boolean,val released: Boolean,val phase: String)
    private val events=ArrayDeque<Event>()
    @Synchronized fun add(name: String,generation: Long=0,proof: RecorderProof=RecorderProof(),phase: String="NONE") {
        if(events.size==256)events.removeFirst()
        events.addLast(Event(now(),name,generation,proof.session,proof.frames,proof.recording,proof.stopped,proof.released,phase))
    }
    @Synchronized fun snapshot()=events.toList()
}
