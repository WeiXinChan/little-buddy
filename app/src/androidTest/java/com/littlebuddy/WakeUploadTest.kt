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
                assertFalse(upload.end())
                assertEquals(1, socket.messages.size)
                assertTrue(upload.ready())
            }
            assertTrue(upload.end())
            assertFalse(upload.end())
            assertTrue(upload.frame(shortArrayOf(99), 1))
            assertEquals(4, socket.messages.size)
            verifyPacket(socket.messages[1], 0, shortArrayOf(11, 12, 13))
            verifyPacket(socket.messages[2], 3, shortArrayOf(14, 15))
            assertEquals(5, JSONObject(socket.messages[3] as String).getInt("samples"))
        }

        val socket = RecordingSocket()
        val revoked = AnimalUpload(2, null, synthetic = false)
        assertTrue(revoked.frame(shortArrayOf(21), 1))
        assertTrue(revoked.start(JSONObject().put("event", "turn.start"), socket))
        revoked.close()
        assertFalse(revoked.ready())
        assertFalse(revoked.end())
        assertTrue(revoked.frame(shortArrayOf(22), 1))
        assertEquals(1, socket.messages.size)
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
        override fun queueSize() = 0L
        override fun send(text: String) = messages.add(text)
        override fun send(bytes: ByteString) = messages.add(bytes)
        override fun close(code: Int, reason: String?) = true
        override fun cancel() = Unit
    }
}
