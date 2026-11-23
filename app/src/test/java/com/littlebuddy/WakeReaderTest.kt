package com.littlebuddy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeNotNull
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Test

class WakeReaderTest {
    @Test fun handoffReplaysAcrossRingWrapAndContinuesWithShortReads() {
        val tail = 49_000
        val input = ShortArray(54_217) { index ->
            if (index < tail + 1600) (index % 29).toShort()
            else (950 + index % 29).let { if (index % 2 == 0) it else -it }.toShort()
        }
        val received = mutableListOf<Short>()
        var commands = 0
        val reader = WakeReader(keyword(tail, at = 53_000), { commands++ }, { error("solo") }) { frame, size ->
            repeat(size) { received.add(frame[it]) }
            true
        }
        reader.use {
            for (offset in input.indices step 247) {
                val frame = input.copyOfRange(offset, minOf(offset + 247, input.size))
                assertTrue(it.accept(frame, frame.size))
            }
        }
        assertEquals(1, commands)
        assertEquals(input.drop(tail - 2560), received)
    }

    @Test fun standbyAndSoloNeverProduceUploadFrames() {
        var solos = 0
        WakeReader(keyword(3200, at = 6400), { error("command") }, { solos++ },
            { _, _ -> error("standby PCM reached upload") }).use {
            repeat(34) { _ -> assertTrue(it.accept(ShortArray(320), 320)) }
            assertFalse(it.accept(ShortArray(320), 320))
        }
        assertEquals(1, solos)
    }

    @Test fun modelTimestampsDriveContinuousAndSoloReplay() {
        val directory = System.getenv("LITTLE_BUDDY_WAKE_FIXTURES")
        assumeNotNull(directory)
        val cases = mapOf("wake" to false, "joined" to true, "gap-0" to true, "gap-120" to true,
            "gap-300" to true, "gap-750" to false)
        for ((name, continuous) in cases) {
            val (at, tail) = File(directory, "$name.hit").readText().trim().split(" ").map(String::toInt)
            val bytes = File(directory, "$name.pcm").readBytes()
            val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
            val input = ShortArray(bytes.size / 2) { buffer.short }
            val received = mutableListOf<Short>()
            var commands = 0
            var solos = 0
            WakeReader(keyword(tail, at), { commands++ }, { solos++ }) { frame, size ->
                repeat(size) { received.add(frame[it]) }
                true
            }.use {
                for (offset in input.indices step 320) {
                    val frame = input.copyOfRange(offset, minOf(offset + 320, input.size))
                    if (!it.accept(frame, frame.size)) break
                }
            }
            assertEquals(name, if (continuous) 1 else 0, commands)
            assertEquals(name, if (continuous) 0 else 1, solos)
            if (continuous) {
                assertEquals(name, input.drop(tail - 2560).take(received.size), received)
            } else assertTrue(name, received.isEmpty())
        }
    }

    private fun keyword(tail: Int, at: Int) = object : WakeKeyword {
        private var received = 0
        override fun accept(samples: ShortArray, count: Int): Long? {
            received += count
            return tail.toLong().takeIf { received >= at }
        }
        override fun close() = Unit
    }
}
