package com.littlebuddy

import androidx.test.platform.app.InstrumentationRegistry
import okhttp3.Request
import okhttp3.WebSocket
import okio.ByteString
import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder

class WakeUploadTest {
    @Test fun packagedNativeModelLoadsAndRejectsSilence() {
        val assets = InstrumentationRegistry.getInstrumentation().targetContext.assets
        SherpaWake(assets).use { model ->
            val silence = ShortArray(320)
            repeat(100) { assertNull(model.accept(silence, silence.size)) }
        }
    }

    @Test fun pendingAndLiveFramesSealInOrderAndCancellationDropsPendingFrames() {
        for (readyBeforeLastFrame in listOf(true, false)) {
            val socket = RecordingSocket()
            val upload = AnimalUpload(1, null, synthetic = false)
            assertTrue(upload.frame(shortArrayOf(11, 12, 13), 3))
            assertTrue(socket.messages.isEmpty())
            assertTrue(upload.start(JSONObject().put("event", "turn.start"), socket))
            if (readyBeforeLastFrame) assertTrue(upload.ready())
            assertTrue(upload.frame(shortArrayOf(14, 15, 16), 2))
            if (!readyBeforeLastFrame) {
                assertEquals(AnimalUpload.Drain.IDLE, upload.drain(sealed = true))
                assertTrue(upload.ready())
            }
            assertEquals(AnimalUpload.Drain.ENDED, upload.drain(sealed = true))
            assertEquals(AnimalUpload.Drain.IDLE, upload.drain(sealed = true))
            assertTrue(upload.frame(shortArrayOf(99), 1))
            assertEquals(3, socket.messages.size)
            verifyPacket(socket.messages[1], 0, shortArrayOf(11, 12, 13, 14, 15))
            assertEquals(5, JSONObject(socket.messages[2] as String).getInt("samples"))
        }
    }

    @Test fun fullBudgetCoalescesShortReadsAndResumesOrCancelsUnderBackpressure() {
        val source = ShortArray(80_000) { (it * 23).toShort() }
        for (readSize in listOf(320, 113)) {
            for (cancel in listOf(false, true)) {
                val socket = RecordingSocket()
                val upload = AnimalUpload(1, null, synthetic = false)
                var offset = 0
                while (offset < source.size) {
                    val end = minOf(offset + readSize, source.size)
                    assertTrue(upload.frame(source.copyOfRange(offset, end), end - offset))
                    offset = end
                }
                assertFalse(upload.frame(shortArrayOf(99), 1))
                assertTrue(upload.start(JSONObject(), socket))
                assertTrue(upload.ready())
                drainBatches(upload)
                assertEquals(251, socket.messages.size)
                assertEquals(AnimalUpload.WIRE_BUDGET.toLong(), socket.queueSize())
                repeat(2) { assertEquals(AnimalUpload.Drain.BLOCKED, upload.drain(sealed = true)) }
                if (cancel) upload.close()
                socket.queued = 0
                assertEquals(if (cancel) AnimalUpload.Drain.IDLE else AnimalUpload.Drain.ENDED,
                    upload.drain(sealed = true))
                assertEquals(AnimalUpload.Drain.IDLE, upload.drain(sealed = true))
                assertEquals(if (cancel) 251 else 252, socket.messages.size)
                repeat(250) { index ->
                    val start = 320 * index
                    verifyPacket(socket.messages[index + 1], start, source.copyOfRange(start, start + 320))
                }
                if (!cancel) assertEquals(80_000, JSONObject(socket.messages.last() as String).getInt("samples"))
            }
        }
    }

    @Test fun cancellationWhileAudioIsQueuedPreventsFurtherPackets() {
        for (cancel in listOf(false, true)) {
            val socket = RecordingSocket()
            val upload = AnimalUpload(1, null, synthetic = false)
            repeat(25) { value -> assertTrue(upload.frame(ShortArray(320) { value.toShort() }, 320)) }
            assertTrue(upload.start(JSONObject(), socket))
            assertTrue(upload.ready())
            socket.queued = AnimalUpload.WIRE_BUDGET - 7L * 646
            assertEquals(AnimalUpload.Drain.BLOCKED, upload.drain(sealed = true))
            assertEquals(8, socket.messages.size)
            if (cancel) upload.close()
            socket.queued = 0
            if (!cancel) {
                assertEquals(AnimalUpload.Drain.MORE, upload.drain(sealed = true))
                assertEquals(AnimalUpload.Drain.ENDED, upload.drain(sealed = true))
                repeat(25) { index ->
                    verifyPacket(socket.messages[index + 1], 320 * index, ShortArray(320) { index.toShort() })
                }
                assertEquals(8000, JSONObject(socket.messages.last() as String).getInt("samples"))
            }
            assertEquals(AnimalUpload.Drain.IDLE, upload.drain(sealed = true))
            assertEquals(if (cancel) 8 else 27, socket.messages.size)
        }
    }

    private fun drainBatches(upload: AnimalUpload) {
        repeat(16) {
            val result = upload.drain(sealed = true)
            if (result != AnimalUpload.Drain.MORE) {
                assertEquals(AnimalUpload.Drain.BLOCKED, result)
                return
            }
        }
        error("Expected bounded drain to reach WebSocket budget")
    }

    private fun verifyPacket(message: Any, offset: Int, expected: ShortArray) {
        val packet = ByteBuffer.wrap((message as ByteString).toByteArray())
        assertEquals(1, packet.get().toInt())
        assertEquals(1, packet.get().toInt())
        assertEquals(offset, packet.int)
        packet.order(ByteOrder.LITTLE_ENDIAN)
        assertArrayEquals(expected, ShortArray(packet.remaining() / 2) { packet.short })
    }

    private class RecordingSocket : WebSocket {
        val messages = mutableListOf<Any>()
        override fun request() = Request.Builder().url("https://localhost/").build()
        var queued = 0L
        override fun queueSize() = queued
        override fun send(text: String) = messages.add(text)
        override fun send(bytes: ByteString): Boolean {
            queued += bytes.size
            return messages.add(bytes)
        }
        override fun close(code: Int, reason: String?) = true
        override fun cancel() = Unit
    }
}
