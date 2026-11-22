package com.littlebuddy

import android.os.Handler
import android.os.Looper
import androidx.test.platform.app.InstrumentationRegistry
import java.nio.ByteBuffer
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class StreamingAudioTest {
    @Test fun nativePlaybackHeadAdvancesBeforeEndAndReleaseFollowsDrain() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val firstHead = CountDownLatch(1)
        val released = CountDownLatch(1)
        val failed = AtomicBoolean()
        val played = AtomicBoolean()
        val stream = CloudPcm({ event, _ ->
            if (event == "playback_head_first_advance") firstHead.countDown()
        })
        val audio = AndroidAudio(
            Handler(Looper.getMainLooper()), frame = { _, _, _ -> },
            failed = { failed.set(true) }, played = { played.set(true) },
            released = { released.countDown() }, diagnostics = null,
        )
        try {
            instrumentation.runOnMainSync { audio.playStream(1, stream) }
            val frameSize = 3_200
            val frames = 8
            repeat(frames) { index ->
                val bytes = ByteBuffer.allocate(6 + frameSize * 2)
                bytes.put(1).put(2).putInt(index * frameSize)
                stream.push(bytes.array())
            }
            assertTrue("Playback head must move before receiving segment.end",
                firstHead.await(2, TimeUnit.SECONDS))
            assertFalse("Unsealed PCM cannot finish playback", played.get())
            stream.seal(frames * frameSize)
            assertTrue("Native audio must release after drain", released.await(3, TimeUnit.SECONDS))
            assertTrue(played.get())
            assertFalse(failed.get())
        } finally {
            stream.abort()
            instrumentation.runOnMainSync { audio.close() }
        }
    }
}
