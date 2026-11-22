package com.littlebuddy

import android.content.Intent
import android.os.SystemClock
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.ImageView
import android.widget.TextView
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.After
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Requires the loopback fake server and adb reverse. Uses native audio on the target. */
class AnimalActivityTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private lateinit var activity: AnimalActivity

    @Before fun launch() {
        val context = instrumentation.targetContext
        activity = instrumentation.startActivitySync(
            Intent(context, AnimalActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        ) as AnimalActivity
    }

    @After fun finish() {
        if (::activity.isInitialized) instrumentation.runOnMainSync { activity.finish() }
    }

    @Test fun threeQuestionsAndReplay() = play(ackFirst = false, delayedRelease = false)

    @Test fun threeQuestionsWithDuplicateReceiptsAndDelayedRelease() =
        play(ackFirst = true, delayedRelease = true)

    @Test fun threeQuestionsWithAckFirst() = play(ackFirst = true, delayedRelease = false)

    @Test fun threeQuestionsWithDelayedRelease() = play(ackFirst = false, delayedRelease = true)

    @Test fun missingRevealReceiptTimesOutWithoutImageOrCount() {
        check("故障注入：扣留揭晓段确认", true)
        tap("开始猜动物")
        await { has("正在听 · 等待模拟输入") }
        submit("告诉我答案")
        await { has("正在播放模拟提示音") }
        await {
            assertFalse(imageVisible())
            assertTrue(has("完成 0 / 3"))
            has("播放或回执超时，请重新开始")
        }
    }

    @Test fun stopsDuringPlaybackAndListeningThenSwitchesToIdle() {
        repeat(2) { attempt ->
            tap("开始猜动物")
            await { has("正在播放模拟提示音") }
            if (attempt == 1) await { has("正在听 · 等待模拟输入") }
            tap("停止")
            await { button("开始猜动物").isEnabled && !imageVisible() }
        }
        tap("开始猜动物")
        await { has("正在听 · 等待模拟输入") }
        submit("我想聊天")
        await { has("本局已结束") && !imageVisible() }
    }

    private fun play(ackFirst: Boolean, delayedRelease: Boolean) {
        check("末 ACK 先到并重复回执", ackFirst)
        check("延迟播放释放通知", delayedRelease)
        tap("开始猜动物")
        await { has("正在听 · 等待模拟输入") }
        for (number in 1..3) {
            assertFalse(read { imageVisible() })
            submit("告诉我答案")
            await { imageVisible() }
            assertTrue(read { has("完成 ${number - 1} / 3") })
            tap("摸摸瓦力")
            await { has("完成 $number / 3") }
            await { has("正在听 · 等待模拟输入") && !imageVisible() }
        }
        submit("再玩")
        await { has("正在听 · 等待模拟输入") && has("完成 0 / 3") }
    }

    private fun submit(text: String) {
        instrumentation.runOnMainSync {
            views().filterIsInstance<EditText>().single().setText(text)
            assertTrue(button("结束录音并提交模拟回答").performClick())
        }
    }

    private fun check(label: String, enabled: Boolean) = instrumentation.runOnMainSync {
        views().filterIsInstance<CheckBox>().single { it.text == label }.isChecked = enabled
    }

    private fun tap(label: String) = instrumentation.runOnMainSync {
        val target = button(label)
        assertTrue(label, target.isEnabled && target.performClick())
    }

    private fun await(condition: () -> Boolean) {
        val end = SystemClock.uptimeMillis() + 10_000
        while (SystemClock.uptimeMillis() < end) {
            if (read(condition)) return
            SystemClock.sleep(25)
        }
        assertTrue(read(condition))
    }

    private fun read(action: () -> Boolean): Boolean {
        var value = false
        instrumentation.runOnMainSync { value = action() }
        return value
    }

    private fun button(label: String) = views().filterIsInstance<Button>().single { it.text == label }
    private fun has(label: String) = views().filterIsInstance<TextView>().any { it.text == label }
    private fun imageVisible() = views().filterIsInstance<ImageView>().any {
        it.contentDescription == "揭晓示意图" && it.visibility == View.VISIBLE
    }

    private fun views(root: View = activity.window.decorView): Sequence<View> = sequence {
        yield(root)
        if (root is ViewGroup) {
            for (index in 0 until root.childCount) yieldAll(views(root.getChildAt(index)))
        }
    }
}
