package com.littlebuddy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit.SECONDS

class AudioWorkerTest {
    @Test fun stopReturnsWhileNativeReleaseIsBlockedAndSlotRemainsOwned() {
        val dispatcher = Executors.newSingleThreadExecutor()
        val callbacks = LinkedBlockingQueue<() -> Unit>()
        val releaseStarted = CountDownLatch(1)
        val allowRelease = CountDownLatch(1)
        val nativeReleased = CountDownLatch(1)
        val events = mutableListOf<String>()
        val worker = AudioWorker(
            { callbacks.add(it) },
            { events += "failed:$it" },
            { events += "played:$it" },
            { events += "released:$it" },
        )
        val nextStarted = CountDownLatch(1)

        fun onDispatcher(action: () -> Unit) {
            dispatcher.submit(action).get(5, SECONDS)
        }

        try {
            onDispatcher {
                worker.submit(1) { operation ->
                    // The native handle has opened and its cleanup is still in progress.
                    releaseStarted.countDown()
                    allowRelease.await()
                    assertTrue(operation.cancelled)
                    nativeReleased.countDown()
                }
            }
            assertTrue(releaseStarted.await(5, SECONDS))
            onDispatcher {
                worker.stop(1)
                val occupied = runCatching { worker.submit(2) { nextStarted.countDown() } }
                assertTrue(occupied.exceptionOrNull() is IllegalStateException)
                assertTrue(events.isEmpty())
            }
            assertEquals(1L, nativeReleased.count)
            assertFalse(nextStarted.await(0, SECONDS))
            assertNull(callbacks.poll())

            allowRelease.countDown()
            val deliverRelease = checkNotNull(callbacks.poll(5, SECONDS))
            assertEquals(0L, nativeReleased.count)
            onDispatcher {
                deliverRelease()
                assertEquals(listOf("released:1"), events)
                worker.submit(2) { nextStarted.countDown() }
            }
            assertTrue(nextStarted.await(5, SECONDS))
        } finally {
            allowRelease.countDown()
            try {
                onDispatcher { worker.close() }
            } finally {
                dispatcher.shutdownNow()
            }
        }
    }
}
