package com.littlebuddy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit.MILLISECONDS
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

    @Test fun recreationWaitsForOldCleanupAndSkipsCancelledQueuedRequests() {
        val cleanupStarted = CountDownLatch(1)
        val allowCleanup = CountDownLatch(1)
        val oldCallbacks = LinkedBlockingQueue<() -> Unit>()
        val callbacks = LinkedBlockingQueue<() -> Unit>()
        val entered = LinkedBlockingQueue<String>()
        val events = mutableListOf<String>()
        val oldEvents = mutableListOf<String>()
        val old = AudioWorker(
            { oldCallbacks.add(it) },
            { oldEvents += "failed:$it" },
            { oldEvents += "played:$it" },
            { oldEvents += "released:$it" },
        )
        val closedWhileQueued = AudioWorker({ callbacks.add(it) }, {}, {}, {})
        val replacement = AudioWorker(
            { callbacks.add(it) },
            { events += "failed:$it" },
            { events += "played:$it" },
            { events += "released:$it" },
        )

        fun nextCallback() = checkNotNull(callbacks.poll(5, SECONDS))

        try {
            old.submit(1) {
                cleanupStarted.countDown()
                allowCleanup.await()
                entered.add("old cleanup finished")
                error("simulate a native operation failing after cleanup")
            }
            assertTrue(cleanupStarted.await(5, SECONDS))
            old.close()
            closedWhileQueued.submit(1) { entered.add("closed request opened") }
            closedWhileQueued.close()
            replacement.submit(1) { entered.add("stopped request opened") }
            replacement.stop(1)
            assertNull(entered.poll(250, MILLISECONDS))
            assertNull(callbacks.poll())

            allowCleanup.countDown()
            checkNotNull(oldCallbacks.poll(5, SECONDS))()
            assertTrue(oldEvents.isEmpty())
            assertEquals("old cleanup finished", entered.poll(5, SECONDS))
            nextCallback()()
            nextCallback()()
            assertEquals(listOf("released:1"), events)

            replacement.submit(2) { entered.add("valid request opened") }
            assertEquals("valid request opened", entered.poll(5, SECONDS))
            nextCallback()()
            assertEquals(listOf("released:1", "played:2", "released:2"), events)
        } finally {
            allowCleanup.countDown()
            old.close()
            closedWhileQueued.close()
            replacement.close()
        }
    }

    @Test fun validReplacementQueuedDuringCleanupRunsAfterRelease() {
        val cleanupStarted = CountDownLatch(1)
        val allowCleanup = CountDownLatch(1)
        val entered = LinkedBlockingQueue<String>()
        val old = AudioWorker({}, {}, {}, {})
        val replacement = AudioWorker({}, {}, {}, {})
        try {
            old.submit(1) {
                cleanupStarted.countDown()
                allowCleanup.await()
                entered.add("old released")
            }
            assertTrue(cleanupStarted.await(5, SECONDS))
            old.close()
            replacement.submit(1) { entered.add("new opened") }
            assertNull(entered.poll(250, MILLISECONDS))
            allowCleanup.countDown()
            assertEquals("old released", entered.poll(5, SECONDS))
            assertEquals("new opened", entered.poll(5, SECONDS))
        } finally {
            allowCleanup.countDown()
            old.close()
            replacement.close()
        }
    }

    @Test fun cancellationBeforeNativeStartCommitRejectsLateStart() {
        val operation = AudioWorker.Operation(1)
        operation.cancel()
        assertFalse(operation.commitStart())
        assertTrue(operation.cancelled)
    }

}
