package com.littlebuddy.v2

/** Body-free observations obtained from native objects, not requested lifecycle state. */
internal data class RecorderProof(val session: Int? = null, val started: Boolean = false,
    val recording: Boolean = false, val frames: Long = 0, val stopped: Boolean = false,
    val released: Boolean = false)
internal data class PlayerProof(val binding: Binding? = null, val observedHead: Long = 0,
    val releasedBinding: Binding? = null, val stop: StopResult? = null)
internal data class NativeEvidence(val recorder: RecorderProof, val player: PlayerProof) {
    fun requireRunning() {
        check(recorder.started && recorder.recording && recorder.frames > 0 && recorder.session != null)
        check(player.binding != null && player.observedHead > 0)
    }
    fun requireReleased(previous: NativeEvidence) {
        previous.requireRunning()
        check(recorder.session == previous.recorder.session && !recorder.recording && recorder.stopped && recorder.released)
        check(player.binding == null && player.releasedBinding == previous.player.binding)
        check(player.stop == StopResult(true, true))
    }
}
