package com.littlebuddy

import android.content.Intent
import android.os.SystemClock
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.TextView
import androidx.test.platform.app.InstrumentationRegistry
import com.littlebuddy.AnimalEvent.*
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test

/** Exercises the private WSS entry with real AudioRecord/AudioTrack and synthetic upload PCM. */
class AnimalPrivateActivityTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val gates = AnimalGates(syntheticCapture = true)
    private lateinit var activity: AnimalActivity

    @After fun finish() {
        if (::activity.isInitialized) onMain { activity.finish() }
    }

    @Test fun stopOrDisconnectClearsAndAllowsOnlyAManualNewGame() {
        val args = InstrumentationRegistry.getArguments()
        val scenario = args.getString("animalScenario")
        assumeTrue("Start scripts/with-private-animal fixture SCENARIO and supply -e animalScenario", scenario != null)
        require(scenario in setOf("asr", "first-pcm", "between", "playing", "release", "late", "blackhole", "disconnect"))
        val context = instrumentation.targetContext
        activity = instrumentation.startActivitySync(Intent(context, AnimalActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK).putExtra("privateGame", true)) as AnimalActivity
        onMain {
            activity.probe = gates
            field("私有 WSS 地址").setText(args.getString("animalUrl", "wss://127.0.0.1:9444/v1/animal"))
            field("游戏设备令牌").setText(args.getString("animalToken", "offlinefixture".repeat(3)))
            button("开始猜动物").performClick()
        }
        await { has("正在听") }
        val spoken = gatesOnMain { gates.count(PCM_HEAD_ADVANCED) }
        onMain {
            gates.held = when (scenario) {
                "playing", "release" -> setOf(PLAYBACK_RELEASE)
                "late" -> setOf(SEGMENT_CONFIRMATION, TURN_COMMIT)
                else -> emptySet()
            }
            activity.injectSyntheticCapture()
        }
        when (scenario) {
            "asr" -> await { gates.count(ASR_UPLOAD_END) == 1 && has("正在等待回复") }
            "first-pcm" -> await { has("正在播放回复") && gates.count(PCM_HEAD_ADVANCED) == spoken }
            "between" -> await { imageVisible() && gates.count(PCM_HEAD_ADVANCED) == spoken + 1 }
            "playing" -> await { gates.count(PCM_HEAD_ADVANCED) > spoken && !imageVisible() }
            "release" -> await { imageVisible() && gates.ready(PLAYBACK_RELEASE) }
            "late" -> await { gates.queued(SEGMENT_CONFIRMATION) == 2 && gates.ready(TURN_COMMIT) }
            "blackhole", "disconnect" -> {
                await { imageVisible() }
                await { button("开始猜动物").isEnabled }
            }
        }

        val delayed = mutableListOf<() -> Unit>()
        onMain {
            if (scenario !in setOf("blackhole", "disconnect")) button("停止").performClick()
            assertFalse(imageVisible())
            assertTrue(has("完成 0 / 3"))
            assertFalse(button("停止").isEnabled)
            if (scenario in setOf("playing", "release")) {
                assertFalse(button("开始猜动物").isEnabled)
            }
            if (scenario == "late") {
                delayed += gates.take(SEGMENT_CONFIRMATION)
                delayed += gates.take(SEGMENT_CONFIRMATION)
                delayed += gates.take(TURN_COMMIT)
            }
        }
        if (scenario in setOf("playing", "release")) {
            await { gates.ready(PLAYBACK_RELEASE) }
            onMain { gates.release(PLAYBACK_RELEASE) }
        }
        await { button("开始猜动物").isEnabled }
        val idle = gatesOnMain { audioActions() }
        // The old provider/transport retires before the manual restart.
        SystemClock.sleep(400)
        onMain {
            assertEquals(idle, audioActions())
            gates.held = emptySet()
            button("开始猜动物").performClick()
        }
        await { has("正在听") }
        onMain {
            val before = audioActions()
            delayed.forEach { it() }
            assertTrue(has("完成 0 / 3"))
            assertFalse(imageVisible())
            assertEquals(before, audioActions())
            assertEquals(idle.first + 1, before.first)
            assertEquals(idle.second + 1, before.second)
        }
    }

    private fun audioActions() = gates.count(CAPTURE_DISPATCH) to gates.count(PCM_HEAD_ADVANCED)

    private fun onMain(action: () -> Unit) = instrumentation.runOnMainSync(action)

    private fun <T> gatesOnMain(read: () -> T): T {
        var value: T? = null
        onMain { value = read() }
        return checkNotNull(value)
    }

    private fun await(condition: () -> Boolean) {
        val until = SystemClock.elapsedRealtime() + 15_000
        do {
            if (gatesOnMain(condition)) return
            SystemClock.sleep(25)
        } while (SystemClock.elapsedRealtime() < until)
        throw AssertionError("Private route condition not reached")
    }

    private fun views(view: View = activity.window.decorView): Sequence<View> = sequence {
        yield(view)
        if (view is ViewGroup) repeat(view.childCount) { yieldAll(views(view.getChildAt(it))) }
    }

    private fun button(text: String) = views().filterIsInstance<Button>().first { it.text.toString() == text }
    private fun field(hint: String) = views().filterIsInstance<EditText>().first { it.hint.toString() == hint }
    private fun has(text: String) = views().filterIsInstance<TextView>().any { it.text.toString() == text }
    private fun imageVisible() = views().filterIsInstance<ImageView>()
        .any { it.contentDescription == "揭晓示意图" && it.visibility == View.VISIBLE }
}
