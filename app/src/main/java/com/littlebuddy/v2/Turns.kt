package com.littlebuddy.v2

/** Semantic decision comes from the ASR/intent adapter, never word length or echo text similarity. */
internal enum class Meaning { STOP, NEW_TURN, BACKCHANNEL, THINKING, CONFIRMED_NOISE, UNKNOWN }
internal interface TurnActions {
    fun suspendOutput()
    fun stopLocallyAndRevoke()
    fun resumeConfirmedNoise()
    fun listen()
    fun clarify()
}
internal class Turns(private val actions: TurnActions) {
    var candidate = false; private set
    fun voiceCandidate() {
        if (!candidate) { candidate = true; actions.suspendOutput() }
        actions.listen()
    }
    fun decide(meaning: Meaning) {
        when (meaning) {
            Meaning.CONFIRMED_NOISE -> if (candidate) actions.resumeConfirmedNoise()
            Meaning.STOP, Meaning.NEW_TURN -> { actions.stopLocallyAndRevoke(); actions.listen() }
            Meaning.BACKCHANNEL, Meaning.THINKING -> actions.listen() // No extra reply or auto-resume.
            Meaning.UNKNOWN -> actions.clarify() // Recognition failure is never proof of noise.
        }
        candidate = false
    }
}
