package com.littlebuddy.v2

/** Owner-thread scene reducer. Tickets prevent queued UI work surviving cancellation. */
internal enum class EyeMood { WAKE, LISTENING, THINKING, SPEAKING, WAITING, FAILURE }
internal class EyeScene {
    @Volatile var generation = 0L; private set
    @Volatile var mood = EyeMood.WAKE; private set
    @Volatile var management = false; private set
    fun event(value: String): Long {
        if (management) return generation
        mood = when (value) {
            "wake" -> EyeMood.WAKE
            "listening" -> EyeMood.LISTENING
            "thinking" -> EyeMood.THINKING
            "speaking" -> EyeMood.SPEAKING
            "waiting", "clarify" -> EyeMood.WAITING
            else -> EyeMood.FAILURE
        }
        return generation
    }
    fun invalidate() { generation++ }
    fun enter() { invalidate(); management = true }
    fun exit() { invalidate(); management = false; mood = EyeMood.WAKE }
    fun accepts(ticket: Long) = ticket == generation && !management
}
