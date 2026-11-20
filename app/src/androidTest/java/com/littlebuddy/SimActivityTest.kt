package com.littlebuddy

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.res.Configuration
import android.os.SystemClock
import android.view.InputDevice
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.AndroidJUnitRunner
import com.littlebuddy.voice.AudioPort
import com.littlebuddy.voice.Deadline
import com.littlebuddy.voice.ReplyPort
import com.littlebuddy.voice.Segment
import com.littlebuddy.voice.Turn
import com.littlebuddy.voice.VoiceRound
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class SimUiRunner : AndroidJUnitRunner() {
    override fun newActivity(loader: ClassLoader, className: String, intent: Intent): Activity {
        if (className == SimActivity::class.java.name && intent.getBooleanExtra("scriptedAudio", false)) {
            return ScriptedSimActivity()
        }
        return super.newActivity(loader, className, intent)
    }
}

class ScriptedSimActivity : SimActivity() {
    internal val ports = ScriptedPorts()
    internal lateinit var coordinator: VoiceRound

    override fun createRound(changed: (VoiceRound.Phase, Int) -> Unit): VoiceRound =
        VoiceRound(ports, ports, Deadline { _, _ -> }, changed).also { coordinator = it }
}

internal class ScriptedPorts : AudioPort, ReplyPort {
    val captures = mutableListOf<Long>()
    val plays = mutableListOf<Long>()
    val stops = mutableListOf<Long>()
    val requests = mutableListOf<Turn>()
    val cancels = mutableListOf<Turn>()

    override fun capture(operation: Long) { captures += operation }
    override fun play(operation: Long, samples: ShortArray) { plays += operation }
    override fun stop(operation: Long) { stops += operation }
    override fun request(turn: Turn) { requests += turn }
    override fun cancel(turn: Turn) { cancels += turn }
}

class SimActivityTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private lateinit var activity: ScriptedSimActivity
    private val ports get() = activity.ports
    private val round get() = activity.coordinator
    private val reply = Segment(1, shortArrayOf(1))

    @Before fun launch() {
        val context = instrumentation.targetContext
        assertEquals("Install the app with adb install -g before running this suite",
            android.content.pm.PackageManager.PERMISSION_GRANTED,
            context.checkSelfPermission(Manifest.permission.RECORD_AUDIO))
        activity = instrumentation.startActivitySync(
            Intent(context, SimActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                .putExtra("scriptedAudio", true),
        ) as ScriptedSimActivity
        instrumentation.waitForIdleSync()
    }

    @After fun finish() {
        if (::activity.isInitialized) onMain { activity.finish() }
        instrumentation.waitForIdleSync()
    }

    @Test fun landscapeTouchStartsAndManualEndCompletesAPlayback() {
        onMain {
            assertEquals(Configuration.ORIENTATION_LANDSCAPE, activity.resources.configuration.orientation)
            assertFalse(button("结束说话").isEnabled)
            assertFalse(button("停止").isEnabled)
        }
        startCapture()
        val turn = endWithSpeech()
        onMain {
            round.segment(turn, reply)
            round.endReply(turn, 1)
            status("正在播放提示音 · 0 / 3")
            val playback = ports.plays.single()
            round.played(playback)
            status("正在切换音频 · 0 / 3")
            assertEquals(1, ports.captures.size)
            round.released(playback)
            status("正在打开麦克风 · 1 / 3")
            assertEquals(2, ports.captures.size)
        }
    }

    @Test fun stopDuringCaptureDiscardsLateFrameAndEndpoint() {
        startCapture()
        tap("停止")
        onMain {
            val capture = ports.captures.single()
            assertEquals(listOf(capture), ports.stops)
            round.captureFrame(capture, true)
            round.endCapture(capture)
            round.released(capture)
            status("点按开始，模拟唤醒 · 0 / 3")
            assertTrue(ports.requests.isEmpty())
        }
    }

    @Test fun stopDuringWaitingAndRestartDiscardsOldReply() {
        startCapture()
        val old = endWithSpeech()
        tap("停止")
        onMain { status("点按开始，模拟唤醒 · 0 / 3") }
        startCapture()
        val current = endWithSpeech()
        onMain {
            round.segment(old, reply)
            round.endReply(old, 1)
            status("正在等待模拟回复 · 0 / 3")
            assertTrue(ports.plays.isEmpty())
            assertEquals(listOf(old), ports.cancels)
            round.segment(current, reply)
            status("正在播放提示音 · 0 / 3")
            assertEquals(1, ports.plays.size)
        }
    }

    @Test fun stopDuringPlaybackRequiresReleaseBeforeRestart() {
        startCapture()
        val old = endWithSpeech()
        onMain {
            round.segment(old, reply)
            round.endReply(old, 1)
            status("正在播放提示音 · 0 / 3")
        }
        tap("停止")
        tap("开始说话")
        onMain {
            val playback = ports.plays.single()
            assertEquals(playback, ports.stops.last())
            round.played(playback)
            status("正在切换音频 · 0 / 3")
            assertEquals(1, ports.captures.size)
            round.released(playback)
            val capture = ports.captures.last()
            assertEquals(2, ports.captures.size)
            round.released(playback)
            round.audioFailed(playback)
            round.captureFrame(capture, true)
            status("正在听 · 0 / 3")
            assertEquals(listOf(old), ports.cancels)
        }
    }

    private fun startCapture() {
        tap("开始说话")
        onMain {
            status("正在打开麦克风 · 0 / 3")
            round.captureFrame(ports.captures.last(), true)
            status("正在听 · 0 / 3")
        }
    }

    private fun endWithSpeech(): Turn {
        tap("结束说话")
        lateinit var turn: Turn
        onMain {
            val capture = ports.captures.last()
            status("正在切换音频 · 0 / 3")
            assertEquals(capture, ports.stops.last())
            round.released(capture)
            status("正在等待模拟回复 · 0 / 3")
            turn = ports.requests.last()
        }
        return turn
    }

    private fun tap(label: String) {
        val point = IntArray(2)
        onMain {
            val target = button(label)
            assertTrue(target.isEnabled)
            assertTrue(target.isShown)
            target.getLocationOnScreen(point)
            point[0] += target.width / 2
            point[1] += target.height / 2
        }
        val down = SystemClock.uptimeMillis()
        for (action in listOf(MotionEvent.ACTION_DOWN, MotionEvent.ACTION_UP)) {
            val event = MotionEvent.obtain(down, SystemClock.uptimeMillis(), action,
                point[0].toFloat(), point[1].toFloat(), 0)
            try {
                event.source = InputDevice.SOURCE_TOUCHSCREEN
                instrumentation.sendPointerSync(event)
            } finally {
                event.recycle()
            }
        }
        instrumentation.waitForIdleSync()
    }

    private fun onMain(action: () -> Unit) {
        // Re-throw assertions on the test thread so the runner reports a test failure.
        var result: Result<Unit>? = null
        instrumentation.runOnMainSync { result = runCatching(action) }
        checkNotNull(result).getOrThrow()
    }

    private fun button(label: String) = views(activity.window.decorView)
        .filterIsInstance<Button>().single { it.text.toString() == label }

    private fun status(label: String) {
        val status = views(activity.window.decorView).filterIsInstance<TextView>()
            .single { it.accessibilityLiveRegion == View.ACCESSIBILITY_LIVE_REGION_POLITE }
        assertEquals(label, status.text.toString())
    }

    private fun views(root: View): Sequence<View> = sequence {
        yield(root)
        if (root is ViewGroup) {
            for (index in 0 until root.childCount) yieldAll(views(root.getChildAt(index)))
        }
    }
}
