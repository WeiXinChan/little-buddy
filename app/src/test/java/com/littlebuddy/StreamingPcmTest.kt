package com.littlebuddy

import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.CountDownLatch
import java.util.concurrent.FutureTask
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test

class StreamingPcmTest {
    private fun packet(offset: Int, vararg samples: Short): ByteArray =
        ByteBuffer.allocate(6 + samples.size * 2).apply {
            put(1).put(2).putInt(offset).order(ByteOrder.LITTLE_ENDIAN)
            samples.forEach { putShort(it) }
        }.array()

    @Test fun offsetsAndFinalLengthMustBeExact() {
        val stream = CloudPcm({ _, _ -> })
        assertThrows(IllegalStateException::class.java) { stream.push(packet(1, 10)) }
        assertTrue(stream.push(packet(0, -10, 20)))
        assertThrows(IllegalStateException::class.java) { stream.push(packet(0, 10)) }
        assertThrows(IllegalStateException::class.java) { stream.push(packet(3, 10)) }
        assertArrayEquals(shortArrayOf(-10, 20), stream.poll())
        assertFalse(stream.ended)
        assertThrows(IllegalStateException::class.java) { stream.seal(1) }
        stream.seal(2)
        assertTrue(stream.ended)
        assertThrows(IllegalStateException::class.java) { stream.seal(2) }
        assertThrows(IllegalStateException::class.java) { stream.push(packet(2, 10)) }
    }

    @Test fun boundedProducerIsReleasedByStopAndDataIsDiscarded() {
        val stream = CloudPcm({ _, _ -> }, capacity = 1)
        stream.push(packet(0, 1))
        val entered = CountDownLatch(1)
        val producer = FutureTask {
            entered.countDown()
            runCatching { stream.push(packet(1, 2)) }.isFailure
        }
        Thread(producer).apply { isDaemon = true }.start()
        assertTrue(entered.await(1, TimeUnit.SECONDS))
        try {
            assertThrows(java.util.concurrent.TimeoutException::class.java) {
                producer.get(100, TimeUnit.MILLISECONDS)
            }
        } finally {
            stream.abort()
        }
        assertTrue(producer.get(1, TimeUnit.SECONDS))
        assertNull(stream.poll())
    }

    private class FakeOutput : PcmOutput {
        val samples = mutableListOf<Short>()
        var started = false
        override var head = 0
        override fun write(samples: ShortArray, offset: Int): Int {
            this.samples += samples[offset]
            return 1 // Exercise partial native writes.
        }
        override fun start() {
            check(!started)
            started = true
        }
    }

    @Test fun slowTailPlaysBeforeSegmentEndAndDrainsInOrder() {
        val events = mutableListOf<Pair<String, Long>>()
        val stream = CloudPcm({ event, op -> events += event to op })
        stream.push(packet(0, 1, 2))
        val output = FakeOutput()
        var now = 0L
        pumpPcm(AudioWorker.Operation(9), stream, 2, output, { now }) {
            now += 100
            assertTrue(output.started)
            output.head = output.samples.size
            if (now == 600L) {
                stream.push(packet(2, 3, 4))
                stream.seal(4)
            }
        }
        assertEquals(listOf<Short>(1, 2, 3, 4), output.samples)
        assertEquals(listOf("playback_requested" to 9L, "playback_head_first_advance" to 9L), events)
    }

    @Test fun sealedShortTailRefillsNativeBufferAfterUnderflow() {
        val stream = CloudPcm({ _, _ -> }).apply { push(packet(0, 1, 2)) }
        val output = FakeOutput()
        var now = 0L
        pumpPcm(AudioWorker.Operation(7), stream, 2, output, { now }) {
            now += 100
            when (now) {
                100L -> output.head = 2
                500L -> {
                    stream.push(packet(2, 3))
                    stream.seal(3)
                }
                600L -> {
                    // A native output that will not resume with the short tail alone.
                    assertEquals(listOf<Short>(1, 2, 3, 0), output.samples)
                    output.head = 4
                }
            }
            check(now <= 600L)
        }
        assertEquals(4, output.head)
    }

    @Test fun shortVerifiedSegmentStartsButUnsealedUnderflowFails() {
        val short = CloudPcm({ _, _ -> }).apply {
            push(packet(0, 1))
            seal(1)
        }
        val output = FakeOutput()
        pumpPcm(AudioWorker.Operation(1), short, 3, output, { 0L }) {
            output.head = output.samples.size
        }
        assertEquals(listOf<Short>(1, 0, 0), output.samples)

        val unsealed = CloudPcm({ _, _ -> }).apply { push(packet(0, 1, 2)) }
        val underrun = FakeOutput()
        var now = 0L
        assertThrows(IllegalStateException::class.java) {
            pumpPcm(AudioWorker.Operation(2), unsealed, 2, underrun, { now }) {
                underrun.head = underrun.samples.size
                now += 500
            }
        }
        assertTrue(underrun.started)
        assertFalse(unsealed.ended)
    }

    @Test fun cancellationDuringPrebufferNeverStartsOutputAndStreamErrorAbortsPlayback() {
        val stream = CloudPcm({ _, _ -> }).apply { push(packet(0, 1)) }
        val output = FakeOutput()
        val operation = AudioWorker.Operation(1)
        pumpPcm(operation, stream, 2, output, { 0L }) { operation.cancel() }
        assertFalse(output.started)

        val active = CloudPcm({ _, _ -> }).apply { push(packet(0, 2)) }
        val output2 = FakeOutput()
        assertThrows(IllegalStateException::class.java) {
            pumpPcm(AudioWorker.Operation(2), active, 1, output2, { 0L }) { active.abort() }
        }
        assertTrue(output2.started)
    }
}
