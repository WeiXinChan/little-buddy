package com.littlebuddy

/** Main-thread fixture. Delivery can be reordered independently of native audio and USB latency. */
internal class AnimalGates(
    override val syntheticCapture: Boolean = false,
    private val input: (() -> (ShortArray, Int) -> Unit)? = null,
) : AnimalProbe {
    override fun wakeInput() = input?.invoke()

    var held = setOf<AnimalEvent>()
    val trace = mutableListOf<AnimalEvent>()
    private val pending = mutableMapOf<AnimalEvent, ArrayDeque<() -> Unit>>()

    override fun deliver(event: AnimalEvent, action: () -> Unit) {
        val deliver = {
            trace += event
            action()
        }
        if (event in held) pending.getOrPut(event) { ArrayDeque() }.addLast(deliver)
        else deliver()
    }

    override fun observe(event: AnimalEvent) {
        trace += event
    }

    fun ready(vararg events: AnimalEvent) = events.all { pending[it]?.isNotEmpty() == true }

    fun queued(event: AnimalEvent) = pending[event]?.size ?: 0

    fun take(event: AnimalEvent): () -> Unit = pending.getValue(event).removeFirst()

    fun release(event: AnimalEvent) = take(event)()

    fun count(event: AnimalEvent) = trace.count { it == event }
}
