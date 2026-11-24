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
    }
    fun speech() {
        if (!awake) return
        if (!speaking) {
            revision++; advance(revision)
            completion = null; probing = false; prompted = false
        }
        soloSent = true
        hasInput = true; speaking = true; lastSpeech = now(); lastInteraction = now()
    }
    fun quiet() { speaking = false }
    fun decision(version: Long, value: Completion) {
        if (!awake || version != revision || !hasInput || speaking) return
        probing = false; completion = value; decisionAt = now()
    }
    fun interaction() { lastInteraction = now() }
    fun tick(outputBusy: Boolean) {
        if (!awake) return
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
