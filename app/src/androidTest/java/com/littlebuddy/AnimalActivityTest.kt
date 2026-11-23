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
import com.littlebuddy.AnimalEvent.*
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Requires the loopback fake server and adb reverse. Uses native audio on the target. */
class AnimalActivityTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private lateinit var activity: AnimalActivity
    private val gates = AnimalGates()

    @Before fun launch() {
        val context = instrumentation.targetContext
        activity = instrumentation.startActivitySync(
            Intent(context, AnimalActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        ) as AnimalActivity
        onMain { activity.probe = gates }
    }

    @After fun finish() {
        if (::activity.isInitialized) instrumentation.runOnMainSync { activity.finish() }
    }

    @Test fun threeQuestionsAndReplay() = play(ackFirst = false, commitFirst = false)

    @Test fun threeQuestionsWithAckAndCommitFirst() =
        play(ackFirst = true, commitFirst = true)

    @Test fun threeQuestionsWithAckFirst() = play(ackFirst = true, commitFirst = false)

    @Test fun threeQuestionsWithCommitFirst() = play(ackFirst = false, commitFirst = true)

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

    @Test fun revealConfirmationCanBeRestoredAndReplayedOnlyOnce() {
        check("末 ACK 先到并重复回执", true)
        tap("开始猜动物")
        await { has("正在听 · 等待模拟输入") }
        onMain { gates.held = setOf(SEGMENT_CONFIRMATION, TURN_COMMIT) }
        submit("告诉我答案")
        await { gates.queued(SEGMENT_CONFIRMATION) == 4 && gates.queued(TURN_COMMIT) == 2 }
        onMain {
            assertFalse(imageVisible())
            assertTrue(has("完成 0 / 3"))
            gates.release(SEGMENT_CONFIRMATION)
            assertTrue(imageVisible())
            gates.release(SEGMENT_CONFIRMATION)
            assertEquals(1, gates.count(IMAGE_SHOWN))
            assertTrue(has("完成 0 / 3"))
        }
    }

    @Test fun stoppingWhileWaitingForCommitAndReplayingOldReleaseCannotAffectNewRound() {
        onMain { gates.held = setOf(TURN_COMMIT, PLAYBACK_RELEASE) }
        tap("开始猜动物")
        await { gates.ready(TURN_COMMIT, PLAYBACK_RELEASE) }
        onMain {
            button("开始猜动物").performClick()
            assertEquals(1, gates.count(TONE_DISPATCH))
            gates.release(PLAYBACK_RELEASE)
            assertTrue(has("正在等待播放回执"))
            assertEquals(0, gates.count(CAPTURE_DISPATCH))
        }
        tap("停止")
        val oldCommit = take(TURN_COMMIT)
        onMain { gates.held = setOf(TONE) }
        tap("开始猜动物")
        await { gates.ready(TONE) }
        val oldTone = take(TONE)
        tap("停止")
        onMain { gates.held = setOf(PLAYBACK_RELEASE) }
        tap("开始猜动物")
        await { gates.ready(PLAYBACK_RELEASE) }
        val oldRelease = take(PLAYBACK_RELEASE)
        tap("停止")
        onMain {
            assertFalse(button("开始猜动物").isEnabled)
            oldRelease()
            assertTrue(button("开始猜动物").isEnabled)
            gates.held = setOf(TURN_COMMIT, PLAYBACK_RELEASE)
        }
        tap("开始猜动物")
        await { gates.ready(TURN_COMMIT, PLAYBACK_RELEASE) }
        onMain {
            val tones = gates.count(TONE_DISPATCH)
            oldCommit()
            oldTone()
            oldRelease()
            assertFalse(imageVisible())
            assertTrue(has("完成 0 / 3"))
            assertEquals(tones, gates.count(TONE_DISPATCH))
            assertEquals(0, gates.count(CAPTURE_DISPATCH))
            gates.release(TURN_COMMIT)
            assertEquals(0, gates.count(CAPTURE_DISPATCH))
            gates.release(PLAYBACK_RELEASE)
        }
        await { has("正在听 · 等待模拟输入") }
        onMain { assertEquals(1, gates.count(CAPTURE_DISPATCH)) }
    }

    @Test fun pausingDuringImageHoldDropsOldImageCommitAndTimerAfterRestart() {
        check("末 ACK 先到并重复回执", true)
        tap("开始猜动物")
        await { has("正在听 · 等待模拟输入") }
        onMain { gates.held = setOf(SEGMENT_CONFIRMATION, TURN_COMMIT, IMAGE_TIMER) }
        submit("告诉我答案")
        await { gates.queued(SEGMENT_CONFIRMATION) == 4 && gates.queued(TURN_COMMIT) == 2 }
        val staleImage = take(SEGMENT_CONFIRMATION)
        onMain {
            staleImage() // Reveal.
            gates.release(SEGMENT_CONFIRMATION) // Duplicate.
            gates.release(SEGMENT_CONFIRMATION) // Celebration.
            gates.release(TURN_COMMIT)
        }
        await { gates.ready(IMAGE_TIMER) }
        val staleCommit = take(TURN_COMMIT)
        val staleTimer = take(IMAGE_TIMER)
        onMain {
            assertTrue(imageVisible())
            instrumentation.callActivityOnPause(activity)
            assertFalse(imageVisible())
            instrumentation.callActivityOnResume(activity)
            assertTrue(button("开始猜动物").isEnabled)
            assertEquals(1, gates.count(CAPTURE_DISPATCH))
            gates.held = setOf(TURN_COMMIT)
        }
        tap("开始猜动物")
        await { gates.ready(TURN_COMMIT) }
        onMain {
            staleImage()
            staleCommit()
            staleTimer()
            assertFalse(imageVisible())
            assertTrue(has("完成 0 / 3"))
            assertEquals(1, gates.count(IMAGE_SHOWN))
            assertEquals(1, gates.count(CAPTURE_DISPATCH))
            gates.release(TURN_COMMIT)
        }
        await { has("正在听 · 等待模拟输入") }
        onMain { assertEquals(2, gates.count(CAPTURE_DISPATCH)) }
    }

    @Test fun staleCaptureFrameCannotAnnounceListeningInTheNextSession() {
        onMain { gates.held = setOf(CAPTURE_FRAME) }
        tap("开始猜动物")
        await { gates.ready(CAPTURE_FRAME) }
        val oldFrame = take(CAPTURE_FRAME)
        tap("停止")
        await { button("开始猜动物").isEnabled }
        tap("开始猜动物")
        await { gates.count(CAPTURE_DISPATCH) == 2 && gates.ready(CAPTURE_FRAME) }
        onMain {
            oldFrame()
            assertFalse(has("正在听 · 等待模拟输入"))
            gates.release(CAPTURE_FRAME)
            assertTrue(has("正在听 · 等待模拟输入"))
        }
    }

    private fun openWithOrder(ackFirst: Boolean, commitFirst: Boolean) {
        check("末 ACK 先到并重复回执", ackFirst)
        onMain { gates.held = setOf(REPLY_END, FINAL_ACK, TURN_COMMIT, PLAYBACK_RELEASE, TAIL_TIMER, CAPTURE_FRAME) }
        tap("开始猜动物")
        await { gates.ready(FINAL_ACK, PLAYBACK_RELEASE) }
        if (ackFirst) {
            onMain {
                assertFalse(gates.ready(REPLY_END))
                gates.release(FINAL_ACK)
            }
            await { gates.ready(REPLY_END) }
            onMain { gates.release(REPLY_END) }
        } else {
            await { gates.ready(REPLY_END) }
            onMain {
                gates.release(REPLY_END)
                gates.release(FINAL_ACK)
            }
        }
        await { gates.queued(TURN_COMMIT) == if (ackFirst) 2 else 1 }
        onMain {
            val first = if (commitFirst) TURN_COMMIT else PLAYBACK_RELEASE
            val second = if (commitFirst) PLAYBACK_RELEASE else TURN_COMMIT
            gates.release(first)
            assertFalse(gates.ready(TAIL_TIMER))
            assertEquals(0, gates.count(CAPTURE_DISPATCH))
            gates.release(second)
            assertTrue(gates.ready(TAIL_TIMER))
            assertEquals(0, gates.count(CAPTURE_DISPATCH))
            assertTrue(gates.trace.indexOf(first) < gates.trace.indexOf(second))
            assertEquals(ackFirst, gates.trace.indexOf(FINAL_ACK) < gates.trace.indexOf(REPLY_END))
            if (gates.ready(TURN_COMMIT)) gates.release(TURN_COMMIT)
            val tail = gates.take(TAIL_TIMER)
            tail()
            tail()
            assertEquals(1, gates.count(CAPTURE_DISPATCH))
            assertFalse(has("正在听 · 等待模拟输入"))
        }
        await { gates.ready(CAPTURE_FRAME) }
        onMain {
            assertFalse(has("正在听 · 等待模拟输入"))
            gates.release(CAPTURE_FRAME)
            assertTrue(has("正在听 · 等待模拟输入"))
            gates.held = setOf(IMAGE_TIMER)
        }
    }

    private fun take(event: AnimalEvent): () -> Unit {
        lateinit var action: () -> Unit
        onMain { action = gates.take(event) }
        return action
    }

    private fun play(ackFirst: Boolean, commitFirst: Boolean) {
        openWithOrder(ackFirst, commitFirst)
        for (number in 1..3) {
            assertFalse(read { imageVisible() })
            submit("告诉我答案")
            await { imageVisible() }
            assertTrue(read { has("完成 ${number - 1} / 3") })
            tap("摸摸瓦力")
            await { has("完成 $number / 3") && gates.ready(IMAGE_TIMER) }
            onMain { gates.release(IMAGE_TIMER) }
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

    private fun onMain(action: () -> Unit) = instrumentation.runOnMainSync(action)

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
