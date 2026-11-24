package com.littlebuddy

import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import com.littlebuddy.v2.*
import org.junit.Assert.*
import org.junit.Assume.assumeNotNull
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.sin

class V2AudioTest {
    @Test fun nativeTrackAckAndStopReleaseUseProductionPump() {
        val thread = HandlerThread("v2-native-test").apply { start() }
        val handler = Handler(thread.looper)
        val finished = CountDownLatch(1)
        val failure = AtomicReference<Throwable?>()
        val binding = Binding(1, "instrumented-native", 1)
        var player: Playback? = null
        handler.post {
            try {
                player = Playback({ AndroidTrack(handler) { error("route changed") } },
                    SystemClock::elapsedRealtime) { ack ->
                    if (ack.head >= 2400) {
                        val result = checkNotNull(player).stop()
                        assertEquals(StopResult(true,true), result)
                        assertFalse(checkNotNull(player).enqueue(AudioPacket(binding, "late", 2400, 2401, shortArrayOf(2))))
                        finished.countDown()
                    }
                }
                checkNotNull(player).bind(binding)
                val tone = ShortArray(2400) { (1200*sin(2*Math.PI*440*it/24000)).toInt().toShort() }
                checkNotNull(player).enqueue(AudioPacket(binding,"tone",0,2400,tone))
            } catch (t: Throwable) { failure.set(t); finished.countDown() }
        }
        val pump = object : Runnable {
            override fun run() {
                try { player?.tick() } catch (t: Throwable) { failure.set(t); finished.countDown() }
                if (finished.count > 0) handler.postDelayed(this,10)
            }
        }
        handler.post(pump)
        try {
            assertTrue("Native ACK must come from head, not elapsed estimate", finished.await(5,TimeUnit.SECONDS))
            failure.get()?.let { throw it }
        } finally {
            val released = CountDownLatch(1)
            handler.post { player?.stop(); released.countDown(); thread.quitSafely() }
            assertTrue(released.await(1,TimeUnit.SECONDS)); thread.join(1000)
        }
    }

    @Test fun backgroundReleasesRecorderAndPlayerWithoutAutomaticResume() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val args = InstrumentationRegistry.getArguments()
        val address = args.getString("v2Address")
        val token = args.getString("v2FixtureToken")
        assumeNotNull(address, token)
        val context = instrumentation.targetContext
        assertEquals("com.littlebuddy.sim.v2", context.packageName)
        instrumentation.uiAutomation.executeShellCommand(
            "pm grant com.littlebuddy.sim.v2 android.permission.RECORD_AUDIO").close()
        val intent = android.content.Intent(context,V2VoiceActivity::class.java)
            .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
        val activity = instrumentation.startActivitySync(intent) as V2VoiceActivity
        fun await(condition: () -> Boolean) {
            val deadline = SystemClock.elapsedRealtime()+4000
            while (!condition() && SystemClock.elapsedRealtime()<deadline) Thread.sleep(20)
            assertTrue(condition())
        }
        try {
            await { activity.hasWindowFocus() }
            instrumentation.runOnMainSync { activity.startVoice(checkNotNull(address),checkNotNull(token)) }
            await { activity.releaseState=="active" }
            // Actual HOME transition, not a direct call to the lifecycle callback.
            context.startActivity(android.content.Intent(android.content.Intent.ACTION_MAIN)
                .addCategory(android.content.Intent.CATEGORY_HOME)
                .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK))
            await { activity.releaseState=="released" }
            context.startActivity(intent)
            await { activity.hasWindowFocus() }
            assertEquals("released",activity.releaseState)
        } finally { instrumentation.runOnMainSync { activity.finish() } }
        // This tests native lifecycle release only. No lock-screen, microphone
        // acoustic, audible output or recognition quality claim follows from it.
    }

    @Test fun realTlsWebsocketFeedsRealTrackAndAckReturnsToBackend() {
        val args = InstrumentationRegistry.getArguments()
        val address = args.getString("v2Address")
        val token = args.getString("v2FixtureToken")
        assumeNotNull(address, token) // Coordinator supplies loopback TLS synthetic fixture only.
        val thread = HandlerThread("v2-wire-test").apply { start() }
        val owner = Handler(thread.looper)
        val played = CountDownLatch(1)
        val failure = AtomicReference<String?>()
        var client: VoiceClient? = null
        owner.post {
            client = VoiceClient(owner, {}, {}, { _, _ -> }, { failure.set("client failed"); played.countDown() },
                observed = { if (it.head >= 12000) played.countDown() })
            checkNotNull(client).connect(checkNotNull(address), checkNotNull(token))
            owner.postDelayed({
                checkNotNull(client).wake()
                checkNotNull(client).frame(ShortArray(320) { 300 }, true)
                checkNotNull(client).quiet()
            }, 300)
        }
        try {
            assertTrue(played.await(8,TimeUnit.SECONDS))
            assertNull(failure.get())
        } finally {
            val released = CountDownLatch(1)
            owner.post { client?.close(); released.countDown(); thread.quitSafely() }
            assertTrue(released.await(1,TimeUnit.SECONDS)); thread.join(1000)
        }
    }
}
