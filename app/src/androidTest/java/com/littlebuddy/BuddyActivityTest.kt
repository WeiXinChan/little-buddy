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
