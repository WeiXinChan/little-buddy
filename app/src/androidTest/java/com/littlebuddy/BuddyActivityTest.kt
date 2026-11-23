package com.littlebuddy

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.test.platform.app.InstrumentationRegistry
import com.littlebuddy.AnimalEvent.CAPTURE_DISPATCH
import com.littlebuddy.AnimalEvent.CAPTURE_FRAME
import com.littlebuddy.AnimalEvent.PCM_HEAD_ADVANCED
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeNotNull
import org.junit.Test

class BuddyActivityTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val gates = AnimalGates(syntheticCapture = true)
    private lateinit var activity: BuddyActivity

    @After fun finish() {
        if (::activity.isInitialized) onMain { activity.finish() }
    }

    @Test fun firstRunTouchAndStopFollowCurrentAudioState() {
        val url = InstrumentationRegistry.getArguments().getString("animalUrl")
        assumeNotNull(url)
        launch()
        onMain {
            field("WSS 服务地址").setText(checkNotNull(url))
            field("设备令牌").setText("offlinefixture".repeat(3))
            button("保存并进入").performClick()
            assertFalse(views().any { it is EditText })
            activity.finish()
        }
        instrumentation.waitForIdleSync()
        launch()
        onMain {
            assertFalse(views().any { it is EditText })
            assertEquals(BuddyMood.IDLE, face().mood)
            gates.held = setOf(CAPTURE_FRAME)
            activity.probe = gates
            button("开始猜动物").performClick()
        }
        await { face().mood == BuddyMood.SPEAKING }
        await { gates.ready(CAPTURE_FRAME) }
        onMain {
            assertTrue(gates.count(PCM_HEAD_ADVANCED) > 0)
            assertEquals(BuddyMood.WAITING, face().mood)
            assertFalse(button("结束录音").isEnabled)
            touchFace(46f)
            gates.held = emptySet()
            gates.release(CAPTURE_FRAME)
            assertEquals(BuddyMood.LISTENING, face().mood)
            assertTrue(button("结束录音").isEnabled)
        }

        // The pat expires after a phase change. The static listening face is restored.
        SystemClock.sleep(750)
        var listening = 0
        onMain {
            listening = faceBitmapHash()
            val dispatches = gates.count(CAPTURE_DISPATCH)
            val heads = gates.count(PCM_HEAD_ADVANCED)
            touchFace(143f)
            assertNotEquals(listening, faceBitmapHash())
            assertEquals(dispatches, gates.count(CAPTURE_DISPATCH))
            assertEquals(heads, gates.count(PCM_HEAD_ADVANCED))
            assertTrue(button("结束录音").isEnabled)
        }
        SystemClock.sleep(750)
        onMain {
            assertEquals(listening, faceBitmapHash())
            button("结束录音").performClick()
            assertEquals(BuddyMood.WAITING, face().mood)
            assertFalse(button("结束录音").isEnabled)
            button("停止").performClick()
            assertEquals(BuddyMood.IDLE, face().mood)
        }
        await { button("开始猜动物").isEnabled }
        onMain {
            gates.held = setOf(CAPTURE_FRAME)
            button("开始猜动物").performClick()
        }
        await { gates.ready(CAPTURE_FRAME) }
        onMain {
            button("停止").performClick()
            gates.held = emptySet()
            gates.release(CAPTURE_FRAME)
            assertEquals(BuddyMood.IDLE, face().mood)
            assertFalse(button("结束录音").isEnabled)
        }
        await { button("开始猜动物").isEnabled }
        var dispatches = 0
        onMain { dispatches = gates.count(CAPTURE_DISPATCH) }
        SystemClock.sleep(300)
        onMain {
            assertEquals(dispatches, gates.count(CAPTURE_DISPATCH))
            assertEquals(BuddyMood.IDLE, face().mood)
        }
    }

    @Test fun switchesModesAndReturnsToIdle() {
        val url = InstrumentationRegistry.getArguments().getString("animalUrl")
        assumeNotNull(url)
        launch()
        onMain {
            field("WSS 服务地址").setText(checkNotNull(url))
            field("设备令牌").setText("offlinefixture".repeat(3))
            button("保存并进入").performClick()
            activity.probe = gates
            button("开始猜动物").performClick()
        }

        await { progress().text == "完成 0 / 3" && button("结束录音").isEnabled }
        onMain { activity.injectSyntheticCapture() }
        await { progress().text == "完成 1 / 3" && button("结束录音").isEnabled }
        onMain {
            gates.held = setOf(AnimalEvent.TURN_COMMIT)
            activity.injectSyntheticCapture()
        }
        await { gates.ready(AnimalEvent.TURN_COMMIT) }
        onMain {
            assertEquals(View.VISIBLE, progress().visibility)
            assertFalse(button("结束录音").isEnabled)
            gates.held = emptySet()
            gates.release(AnimalEvent.TURN_COMMIT)
        }
        await { progress().visibility == View.GONE && button("结束录音").isEnabled }

        onMain { activity.injectSyntheticCapture() }
        await { progress().visibility == View.GONE && button("结束录音").isEnabled }
        onMain { activity.injectSyntheticCapture() }
        await { progress().visibility == View.VISIBLE && progress().text == "完成 0 / 3" &&
            button("结束录音").isEnabled }
        onMain { activity.injectSyntheticCapture() }
        await { face().mood == BuddyMood.IDLE && !button("停止").isEnabled }
    }

    @Test fun nativeWakeFlowsThroughProductAudioAndTlsAsr() {
        val url = checkNotNull(InstrumentationRegistry.getArguments().getString("animalUrl"))
        val events = mutableListOf<AnimalEvent>()
        val inputs = ArrayDeque(listOf("gap-120", "wake", "command-alone"))
        val fixtures = inputs.associateWith(::wakeFixture)
        launch()
        onMain {
            activity.probe = object : AnimalProbe {
                override fun deliver(event: AnimalEvent, action: () -> Unit) = action()
                override fun observe(event: AnimalEvent) { events.add(event) }
                override fun wakeInput(): (ShortArray, Int) -> Unit {
                    val pcm = if (inputs.isEmpty()) ShortArray(0) else fixtures.getValue(inputs.removeFirst())
                    var offset = 0
                    return { samples, count ->
                        repeat(count) { i -> samples[i] = pcm.getOrElse(offset++) { 0 } }
                    }
                }
            }
            field("WSS 服务地址").setText(url)
            field("设备令牌").setText("offlinefixture".repeat(3))
            button("保存并进入").performClick()
        }

        // The 500 ms leading silence is inside the native input fixture.
        SystemClock.sleep(300)
        onMain { assertFalse(AnimalEvent.OPEN_SOCKET in events) }
        await { events.count { it == AnimalEvent.ASR_UPLOAD_END } == 1 && button("结束录音").isEnabled }
        onMain {
            assertFalse(AnimalEvent.WAKE_PROMPT in events)
            button("停止").performClick()
        }
        await { events.count { it == AnimalEvent.ASR_UPLOAD_END } == 2 && button("结束录音").isEnabled }
        onMain {
            val prompt = events.indexOf(AnimalEvent.WAKE_PROMPT)
            val promptReleased = events.indexOf(AnimalEvent.WAKE_PROMPT_RELEASED)
            val secondConnection = events.lastIndexOf(AnimalEvent.OPEN_SOCKET)
            assertTrue(prompt > 0 && events[prompt - 1] == AnimalEvent.WAKE_CAPTURE_RELEASED)
            assertTrue(promptReleased > prompt && events[promptReleased + 1] == AnimalEvent.WAKE_CAPTURE)
            assertTrue(secondConnection > promptReleased)
            assertEquals(2, events.count { it == AnimalEvent.OPEN_SOCKET })
            button("停止").performClick()
        }
    }

    @Test fun nativeWakeRejectsRevokedCallbacks() {
        val args = InstrumentationRegistry.getArguments()
        val url = checkNotNull(args.getString("animalUrl"))
        val marker = AnimalEvent.valueOf(checkNotNull(args.getString("wakeGate")))
        val revoke = checkNotNull(args.getString("wakeRevoke"))
        require(marker in setOf(AnimalEvent.WAKE_COMMAND, AnimalEvent.ASR_READY, AnimalEvent.PCM_SEGMENT))
        require(revoke in setOf("stop", "background", "sleep"))
        val pcm = wakeFixture("gap-120")
        var captures = 0
        val gate = AnimalGates(input = {
            val input = if (captures++ == 0) pcm else ShortArray(0)
            var offset = 0
            val read: (ShortArray, Int) -> Unit = { samples, count ->
                repeat(count) { index -> samples[index] = input.getOrElse(offset++) { 0 } }
            }
            read
        })
        launch()
        onMain {
            activity.probe = gate
            gate.held = setOf(marker)
            field("WSS 服务地址").setText(url)
            field("设备令牌").setText("offlinefixture".repeat(3))
            button("保存并进入").performClick()
        }

        await {
            gate.ready(marker) && button("停止").isEnabled &&
                (marker != AnimalEvent.PCM_SEGMENT || gate.count(AnimalEvent.PCM_BUFFERED) > 0)
        }
        lateinit var late: () -> Unit
        var connections = 0
        var uploadsEnded = 0
        var playbackHeads = 0
        onMain {
            late = gate.take(marker)
            gate.held = emptySet()
            connections = gate.count(AnimalEvent.OPEN_SOCKET)
            uploadsEnded = gate.count(AnimalEvent.ASR_UPLOAD_END)
            playbackHeads = gate.count(AnimalEvent.PCM_HEAD_ADVANCED)
            assertEquals(if (marker == AnimalEvent.WAKE_COMMAND) 0 else 1, connections)
            assertEquals(if (marker == AnimalEvent.PCM_SEGMENT) 1 else 0, uploadsEnded)
            assertEquals(0, playbackHeads)
        }
        val power = activity.getSystemService(android.os.PowerManager::class.java)
        try {
            when (revoke) {
                "stop" -> {
                    onMain { button("停止").performClick() }
                    await { captures == 2 }
                }
                "background" -> {
                    onMain { assertTrue(activity.moveTaskToBack(true)) }
                    await { !button("停止").isEnabled }
                }
                "sleep" -> {
                    shell("input keyevent KEYCODE_SLEEP")
                    await { !power.isInteractive && !button("停止").isEnabled }
                    val keyguard = activity.getSystemService(android.app.KeyguardManager::class.java)
                    val run = args.getString("wakeRun").orEmpty()
                    android.util.Log.i("WakeProbe",
                        "run=$run gate=$marker screen_interactive=false keyguard_locked=${keyguard.isKeyguardLocked}")
                }
            }
            onMain { late() }
            SystemClock.sleep(400)
            onMain {
                assertEquals(connections, gate.count(AnimalEvent.OPEN_SOCKET))
                assertEquals(uploadsEnded, gate.count(AnimalEvent.ASR_UPLOAD_END))
                assertEquals(playbackHeads, gate.count(AnimalEvent.PCM_HEAD_ADVANCED))
                assertFalse(button("结束录音").isEnabled)
                android.util.Log.i("WakeProbe",
                    "late_gate=$marker revoke=$revoke delivered=1 connections_delta=0 seals_delta=0 playback_delta=0")
            }
        } finally {
            if (revoke == "sleep") {
                shell("input keyevent KEYCODE_WAKEUP")
                shell("wm dismiss-keyguard")
            }
        }
    }

    private fun wakeFixture(name: String): ShortArray {
        val assets = instrumentation.context.assets
        val bytes = assets.open("wake/$name.pcm").use { it.readBytes() }
        val buffer = java.nio.ByteBuffer.wrap(bytes).order(java.nio.ByteOrder.LITTLE_ENDIAN)
        return ShortArray(bytes.size / 2) { buffer.short }
    }

    private fun shell(command: String): String = android.os.ParcelFileDescriptor.AutoCloseInputStream(
        instrumentation.uiAutomation.executeShellCommand(command),
    ).bufferedReader().use { it.readText() }

    private fun progress() = views().filterIsInstance<TextView>().single { it.text.startsWith("完成 ") }

    private fun launch() {
        activity = instrumentation.startActivitySync(Intent(instrumentation.targetContext, BuddyActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as BuddyActivity
    }

    private fun onMain(action: () -> Unit) = instrumentation.runOnMainSync(action)

    private fun await(condition: () -> Boolean) {
        val until = SystemClock.elapsedRealtime() + 15_000
        do {
            var ready = false
            onMain { ready = condition() }
            if (ready) return
            SystemClock.sleep(25)
        } while (SystemClock.elapsedRealtime() < until)
        throw AssertionError("Buddy audio stage did not arrive")
    }

    private fun views(view: View = activity.window.decorView): Sequence<View> = sequence {
        yield(view)
        if (view is ViewGroup) repeat(view.childCount) { yieldAll(views(view.getChildAt(it))) }
    }

    private fun face() = views().filterIsInstance<BuddyFace>().single()
    private fun field(hint: String) = views().filterIsInstance<EditText>().single { it.hint.toString() == hint }
    private fun button(text: String) = views().filterIsInstance<Button>().single { it.text.toString() == text }

    private fun touchFace(vertical: Float) {
        val face = face()
        val scale = minOf(face.width / 400f, face.height / 230f)
        val y = face.height / 2f + (vertical - 115f) * scale
        for (action in listOf(MotionEvent.ACTION_DOWN, MotionEvent.ACTION_UP)) {
            val now = SystemClock.uptimeMillis()
            val event = MotionEvent.obtain(now, now, action, face.width / 2f, y, 0)
            try {
                assertTrue(face.dispatchTouchEvent(event))
            } finally {
                event.recycle()
            }
        }
    }

    private fun faceBitmapHash(): Int {
        val face = face()
        val bitmap = Bitmap.createBitmap(face.width, face.height, Bitmap.Config.ARGB_8888)
        try {
            face.draw(Canvas(bitmap))
            val pixels = IntArray(bitmap.width * bitmap.height)
            bitmap.getPixels(pixels, 0, bitmap.width, 0, 0, bitmap.width, bitmap.height)
            return pixels.contentHashCode()
        } finally {
            bitmap.recycle()
        }
    }
}
