package com.littlebuddy

import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicReference

// Each dispatcher tracks its request. The process executor owns native audio across Activity lifetimes.
internal class AudioWorker(
    private val post: (() -> Unit) -> Unit,
    private val failed: (Long) -> Unit,
    private val played: (Long) -> Unit,
    private val released: (Long) -> Unit,
) {
    internal class Operation(val id: Long) {
        private enum class State { OPENING, START_COMMITTED, CANCELLED }

        private val state = AtomicReference(State.OPENING)
        val cancelled get() = state.get() == State.CANCELLED

        fun cancel() {
            state.set(State.CANCELLED)
        }

        // Orders cancellation against start without holding a lock across a native call.
        fun commitStart() = state.compareAndSet(State.OPENING, State.START_COMMITTED)
    }

    private var active: Operation? = null
    var closed = false
        private set

    fun stop(id: Long) {
        val operation = active ?: return
        if (operation.id == id) operation.cancel()
    }

    fun close() {
        closed = true
        active?.let { stop(it.id) }
    }

    // The task owns any partially opened handle and cleans it up before returning.
    fun submit(id: Long, task: (Operation) -> Unit) {
        check(active == null && !closed)
        val operation = Operation(id)
        active = operation
        processAudio.execute {
            val success = try {
                if (!operation.cancelled) task(operation)
                true
            } catch (_: RuntimeException) {
                false
            }
            post {
                if (!closed) {
                    if (!operation.cancelled) {
                        if (success) played(id) else failed(id)
                    }
                    active = null
                    released(id)
                }
            }
        }
    }

    private companion object {
        // A queued request cannot touch native audio until the previous task finishes cleanup.
        val processAudio = Executors.newSingleThreadExecutor { task ->
            Thread(task, "little-buddy-audio").apply { isDaemon = true }
        }
    }
}
