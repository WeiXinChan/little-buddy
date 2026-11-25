package com.littlebuddy.v2

/** One budget per child connection; duplicate listening/wake events cannot extend an active turn. */
internal class PlaybackBudget(private val now: () -> Long, private val limitSeconds: Int) {
    private var start: Long? = null
    init { require(limitSeconds in 60..600) }
    fun begin() { if (start == null) start = now() }
    fun expired(): Boolean {
        val first = start ?: return false
        val current = now()
        return current < first || current - first >= limitSeconds * 1000L
    }
}
