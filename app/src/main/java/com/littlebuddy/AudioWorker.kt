package com.littlebuddy

import java.util.concurrent.Executors

// The dispatcher owns the slot. Native audio and its cleanup run only on the worker.
internal class AudioWorker(
    private val post: (() -> Unit) -> Unit,
    private val failed: (Long) -> Unit,
    private val played: (Long) -> Unit,
    private val released: (Long) -> Unit,
) {
    internal class Operation(val id: Long) {
        @Volatile var cancelled = false
    }

    private val executor = Executors.newSingleThreadExecutor()
    private var active: Operation? = null
    var closed = false
        private set

    fun stop(id: Long) {
        val operation = active ?: return
        if (operation.id == id) operation.cancelled = true
    }

    fun close() {
        closed = true
        active?.let { stop(it.id) }
        executor.shutdown()
    }

    // The task owns any partially opened handle and cleans it up before returning.
    fun submit(id: Long, task: (Operation) -> Unit) {
        check(active == null && !closed)
        val operation = Operation(id)
        active = operation
        executor.execute {
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
}
