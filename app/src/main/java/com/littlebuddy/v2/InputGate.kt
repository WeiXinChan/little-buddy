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
    val awaitingResponse:Boolean get()=awake && responsePending
    private var inputPending = false // Distinguish a captured expression from a wake-solo response.
    fun checkResponseDeadline() {
        if (responsePending && thinkingAt == null) check(now() < responseDeadline) { "first response expired" }
    }
    fun noResponseExpected() { responsePending = false; inputPending = false }
    fun effectivePlayed() { responsePending = false; inputPending = false }
    var revision = 0L; private set
    var awake = false; private set
    fun managementWaiting(version: Long) {
        require(version >= revision)
        revision = version; awake = false; hasInput = false; speaking = false; probing = false
        completion = null; responsePending = false; inputPending = false; thinkingAt = null; prompted = false; soloSent = false
    }
    private var lastSpeech = 0L
    val capturedLastSpeechBootMs:Long get()=lastSpeech // Read-only: original capture boundary, never a phase timestamp.
    private var lastInteraction = 0L
    private var wakeAt = 0L
    private var speaking = false
    private var hasInput = false
    private var probing = false
    private var completion: Completion? = null
    val endpointCompletion:Completion? get()=completion
    private var decisionAt = 0L
    private var prompted = false
    private var soloSent = false
    fun wake(observedAt: Long = now()) {
        require(observedAt in 0..now())
        if (awake) return
        awake = true; wakeAt = observedAt; lastInteraction = now()
        hasInput = false; speaking = false; soloSent = false; prompted = false
        completion = null; probing = false
        responsePending = false; inputPending = false; thinkingAt = null; excludedThinkingMs = 0
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
        responsePending = true; inputPending = true; responseDeadline = lastSpeech + 15000
        thinkingAt = null; excludedThinkingMs = 0
    }
    fun quiet() { speaking = false }
    fun decision(version: Long, value: Completion):Boolean {
        if (!awake || version != revision || !hasInput || speaking) return false
        checkResponseDeadline()
        if (value == Completion.THINKING) {
            if (thinkingAt == null) thinkingAt = now()
        } else thinkingAt?.let { start ->
            val excluded = now() - start
            excludedThinkingMs += excluded; responseDeadline += excluded; thinkingAt = null
        }
        probing = false; completion = value; decisionAt = now()
        return true
    }
    /** Terminal non-response for this captured expression, NOT noise or effective playback.
     * Check the original deadline before clearing; no renewal of deadline/capture/idle/TTL. */
    fun unrecognized(version: Long): Boolean {
        if (!awake || version != revision || speaking || !inputPending || !responsePending) return false
        checkResponseDeadline()
        hasInput=false; probing=false; completion=null; responsePending=false; inputPending=false
        thinkingAt=null; prompted=false; soloSent=true
        return true
    }
    fun interaction() { lastInteraction = now() }
    fun tick(outputBusy: Boolean) {
        if (!awake) return
        checkResponseDeadline()
        val time = now()
        if (!hasInput && !soloSent && time - wakeAt >= waits.solo) { soloSent = true; responsePending = true; responseDeadline = wakeAt + 15000; checkResponseDeadline(); solo() }
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
