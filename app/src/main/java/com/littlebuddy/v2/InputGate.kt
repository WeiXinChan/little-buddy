package com.littlebuddy.v2

internal data class Waits(val complete: Long = 1000, val incomplete: Long = 2500,
                         val thinking: Long = 10000, val probe: Long = 300,
                         val solo: Long = 500, val idle: Long = 60000) {
    init {
        require(complete in 800..1200 && incomplete in 2000..3000 && thinking in 8000..12000)
        require(probe in 100..complete && solo in 300..800 && idle > thinking)
    }
}
internal enum class Completion { COMPLETE, INCOMPLETE, THINKING }

/** Production endpoint owner. Silence only requests a semantic probe, never seals
 * an incomplete/thinking expression. Every continuation invalidates old decisions.
 */
internal class InputGate(private val waits: Waits, private val now: () -> Long,
                         private val advance: (Long) -> Unit, private val probe: (Long) -> Unit,
                         private val seal: (Long) -> Unit, private val solo: () -> Unit,
                         private val askOnce: () -> Unit, private val idle: () -> Unit) {
    var responseDeadline = 0L; private set
    var excludedThinkingMs = 0L; private set
    private var thinkingAt: Long? = null
    private var responsePending = false
    fun checkResponseDeadline() {
        if (responsePending && thinkingAt == null) check(now() < responseDeadline) { "first response expired" }
    }
    fun noResponseExpected() { responsePending = false }
    fun effectivePlayed() { responsePending = false }
    var revision = 0L; private set
    var awake = false; private set
    private var lastSpeech = 0L
    private var lastInteraction = 0L
    private var wakeAt = 0L
    private var speaking = false
    private var hasInput = false
    private var probing = false
    private var completion: Completion? = null
    private var decisionAt = 0L
    private var prompted = false
    private var soloSent = false
    fun wake() {
        awake = true; wakeAt = now(); lastInteraction = now()
        hasInput = false; speaking = false; soloSent = false; prompted = false
        completion = null; probing = false
        responsePending = false; thinkingAt = null; excludedThinkingMs = 0
    }
    fun speech(observedAt: Long = now()) {
        if (!awake) return
        require(observedAt <= now() && observedAt >= 0) { "future capture boundary" }
        if (!speaking) {
            revision++; advance(revision)
            completion = null; probing = false; prompted = false
        }
        soloSent = true
        hasInput = true; speaking = true; lastSpeech = maxOf(lastSpeech, observedAt); lastInteraction = now()
        responsePending = true; responseDeadline = lastSpeech + 15000
        thinkingAt = null; excludedThinkingMs = 0
    }
    fun quiet() { speaking = false }
    fun decision(version: Long, value: Completion) {
        if (!awake || version != revision || !hasInput || speaking) return
        checkResponseDeadline()
        if (value == Completion.THINKING) {
            if (thinkingAt == null) thinkingAt = now()
        } else thinkingAt?.let { start ->
            val excluded = now() - start
            excludedThinkingMs += excluded; responseDeadline += excluded; thinkingAt = null
        }
        probing = false; completion = value; decisionAt = now()
    }
    fun interaction() { lastInteraction = now() }
    fun tick(outputBusy: Boolean) {
        if (!awake) return
        checkResponseDeadline()
        val time = now()
        if (!hasInput && !soloSent && time - wakeAt >= waits.solo) { soloSent = true; solo() }
        if (hasInput && !speaking) {
            if (completion == null && !probing && time - lastSpeech >= waits.probe) {
                probing = true; probe(revision)
            }
            when (completion) {
                Completion.COMPLETE -> if (time - lastSpeech >= waits.complete) {
                    hasInput = false; completion = null; seal(revision)
                }
                Completion.INCOMPLETE -> if (time - maxOf(lastSpeech, decisionAt) >= waits.incomplete) {
                    completion = null; probing = true; probe(revision) // Re-evaluate; never force reply.
                }
                Completion.THINKING -> if (time - maxOf(lastSpeech, decisionAt) >= waits.thinking && !prompted) {
                    prompted = true; askOnce() // At most one contextual invitation; no forced seal.
                }
                null -> Unit
            }
        }
        if (!hasInput && !speaking && !outputBusy && time - lastInteraction >= waits.idle) {
            awake = false; idle()
        }
    }
}
