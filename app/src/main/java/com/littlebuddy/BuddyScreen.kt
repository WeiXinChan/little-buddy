package com.littlebuddy

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.os.Bundle
import android.os.SystemClock
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.Button
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import kotlin.math.sin

internal enum class BuddyMood { IDLE, WAITING, LISTENING, SPEAKING, ERROR }

internal fun View.buddyDp(value: Int) = (value * resources.displayMetrics.density + .5f).toInt()

internal fun View.applyBuddyInsets(padding: Int) {
    val margin = buddyDp(padding)
    @Suppress("DEPRECATION")
    setOnApplyWindowInsetsListener { view, insets ->
        val cutout = if (android.os.Build.VERSION.SDK_INT >= 28) insets.displayCutout else null
        view.setPadding(
            maxOf(insets.systemWindowInsetLeft, cutout?.safeInsetLeft ?: 0) + margin,
            maxOf(insets.systemWindowInsetTop, cutout?.safeInsetTop ?: 0) + margin,
            maxOf(insets.systemWindowInsetRight, cutout?.safeInsetRight ?: 0) + margin,
            maxOf(insets.systemWindowInsetBottom, cutout?.safeInsetBottom ?: 0) + margin,
        )
        insets
    }
    requestApplyInsets()
}

internal class BuddyScreen(context: Context, begin: () -> Unit, cancel: () -> Unit, seal: () -> Unit) {
    val root = LinearLayout(context).apply {
        orientation = LinearLayout.VERTICAL
        gravity = Gravity.CENTER_HORIZONTAL
        setBackgroundColor(0xffe8f0e2.toInt())
        applyBuddyInsets(8)
    }
    val face = BuddyFace(context)
    val status = label(21f).apply {
        text = "准备好了"
        accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
    }
    val count = label(16f).apply { text = "完成 0 / 3" }
    val caption = label(16f).apply { visibility = View.GONE }
    val picture = ImageView(context).apply {
        contentDescription = "揭晓示意图"
        visibility = View.GONE
        scaleType = ImageView.ScaleType.FIT_CENTER
    }
    val start = button("开始猜动物", 0xff156956.toInt(), begin)
    val finish = button("结束录音", 0xff31556b.toInt(), seal)
    val stop = button("停止", 0xff9b392e.toInt(), cancel)

    init {
        val stage = FrameLayout(context).apply {
            addView(face, FrameLayout.LayoutParams(-1, -1))
            addView(picture, FrameLayout.LayoutParams(root.buddyDp(100), root.buddyDp(100),
                Gravity.END or Gravity.CENTER_VERTICAL))
        }
        val controls = LinearLayout(context).apply {
            gravity = Gravity.CENTER
            for (button in listOf(start, finish, stop)) {
                addView(button, LinearLayout.LayoutParams(0, -2, 1f).apply {
                    marginStart = root.buddyDp(4)
                    marginEnd = root.buddyDp(4)
                })
            }
        }
        root.addView(stage, LinearLayout.LayoutParams(-1, 0, 1f))
        root.addView(status)
        root.addView(count)
        root.addView(controls, LinearLayout.LayoutParams(-1, -2))
    }

    private fun label(size: Float) = TextView(root.context).apply {
        textSize = size
        gravity = Gravity.CENTER
        setTextColor(0xff173f3b.toInt())
    }

    private fun button(title: String, color: Int, action: () -> Unit) = Button(root.context).apply {
        text = title
        textSize = 18f
        minHeight = buddyDp(56)
        setTextColor(Color.WHITE)
        backgroundTintList = ColorStateList(
            arrayOf(intArrayOf(-android.R.attr.state_enabled), intArrayOf()),
            intArrayOf(0xff596a65.toInt(), color),
        )
        setOnClickListener { action() }
    }
}

internal class BuddyFace(context: Context) : View(context) {
    var mood = BuddyMood.IDLE
        set(value) {
            field = value
            invalidate()
        }

    private enum class Touch { PAT, POKE }

    private val eyeCenters = floatArrayOf(150f, 250f)
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val smile = Path()
    private val mouth = RectF()
    private val blinkingFrom = SystemClock.uptimeMillis()
    private var touch: Touch? = null
    private var touchX = 200f
    private var touchUntil = 0L

    init {
        contentDescription = "瓦力的脸"
        isFocusable = true
        isClickable = true
    }

    fun clearTouch() {
        touch = null
        invalidate()
    }

    private fun react(action: Touch, x: Float) {
        touch = action
        touchX = x
        touchUntil = SystemClock.uptimeMillis() + 650
        invalidate()
    }

    override fun onInitializeAccessibilityNodeInfo(info: AccessibilityNodeInfo) {
        super.onInitializeAccessibilityNodeInfo(info)
        info.addAction(AccessibilityNodeInfo.AccessibilityAction(ACTION_PAT, "摸头"))
        info.addAction(AccessibilityNodeInfo.AccessibilityAction(ACTION_POKE, "戳脸"))
    }

    override fun performAccessibilityAction(action: Int, arguments: Bundle?): Boolean = when (action) {
        ACTION_PAT -> performClick()
        ACTION_POKE -> {
            react(Touch.POKE, 254f)
            true
        }
        else -> super.performAccessibilityAction(action, arguments)
    }

    override fun performClick(): Boolean {
        super.performClick()
        react(Touch.PAT, 200f)
        return true
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (event.actionMasked == MotionEvent.ACTION_DOWN) {
            val scale = faceScale()
            if (scale <= 0f) return false
            val x = (event.x - (width - 400f * scale) / 2) / scale
            val y = (event.y - (height - 230f * scale) / 2) / scale
            if (x !in 66f..334f || y !in 4f..215f) return false
            react(if (y < 84f) Touch.PAT else Touch.POKE, x.coerceIn(112f, 288f))
        }
        return true
    }

    private fun faceScale() = minOf(width / 400f, height / 230f)

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val now = SystemClock.uptimeMillis()
        if (now >= touchUntil) touch = null
        val reaction = touch
        val scale = faceScale()
        val elapsed = now - blinkingFrom
        val lift = if (mood == BuddyMood.IDLE) (sin(elapsed / 680.0) * 2).toFloat() else 0f
        val checkpoint = canvas.save()
        canvas.translate((width - 400f * scale) / 2, (height - 230f * scale) / 2 + lift * scale)
        canvas.scale(scale, scale)
        fun box(left: Float, top: Float, right: Float, bottom: Float, radius: Float, color: Int) {
            paint.color = color
            canvas.drawRoundRect(left, top, right, bottom, radius, radius, paint)
        }

        val indicator = when (mood) {
            BuddyMood.IDLE -> 0xff9ce2c4.toInt()
            BuddyMood.WAITING -> 0xffffcf72.toInt()
            BuddyMood.LISTENING -> 0xff71eccc.toInt()
            BuddyMood.SPEAKING -> 0xffa8ceff.toInt()
            BuddyMood.ERROR -> 0xffffa08e.toInt()
        }
        box(183f, 19f, 217f, 75f, 16f, 0xff39786c.toInt())
        box(184f, 7f, 216f, 32f, 12f, indicator)
        box(53f, 104f, 97f, 173f, 21f, 0xffbb692d.toInt())
        box(303f, 104f, 347f, 173f, 21f, 0xffbb692d.toInt())
        box(74f, 45f, 326f, 218f, 55f, 0xffffc86a.toInt())
        box(91f, 62f, 309f, 197f, 41f, 0xff173f3b.toInt())

        val blink = mood == BuddyMood.IDLE && elapsed % 4600 in 4300L..4450L
        for (center in eyeCenters) {
            val lid = when {
                reaction == Touch.PAT || blink -> 4f
                reaction == Touch.POKE && (center < 200f) == (touchX < 200f) -> 5f
                mood == BuddyMood.WAITING -> 9f
                mood == BuddyMood.ERROR -> 12f
                mood == BuddyMood.LISTENING -> 29f
                else -> 21f
            }
            box(center - 13, 119 - lid, center + 13, 119 + lid, 13f, indicator)
        }

        paint.color = indicator
        if (reaction != null || mood == BuddyMood.IDLE) {
            smile.rewind()
            smile.moveTo(177f, 153f)
            smile.quadTo(200f, if (reaction == null) 176f else 185f, 223f, 153f)
            paint.style = Paint.Style.STROKE
            paint.strokeWidth = 6f
            paint.strokeCap = Paint.Cap.ROUND
            canvas.drawPath(smile, paint)
            paint.style = Paint.Style.FILL
        } else if (mood == BuddyMood.WAITING) {
            val dot = (elapsed / 170 % 3).toInt()
            repeat(3) { canvas.drawCircle(185f + it * 15, 155f, if (it == dot) 5f else 3f, paint) }
        } else {
            val opening = if (mood == BuddyMood.SPEAKING) 9f + 6f * sin(elapsed / 74.0).toFloat() else 4f
            mouth.set(183f, 155f - opening, 217f, 155f + opening)
            canvas.drawOval(mouth, paint)
        }
        if (reaction != null) {
            paint.color = 0xffffa18a.toInt()
            val y = if (reaction == Touch.PAT) 41f else 153f
            canvas.drawCircle(touchX, y, 8f, paint)
        }
        canvas.restoreToCount(checkpoint)
        if (isShown && windowVisibility == VISIBLE &&
            (reaction != null || mood == BuddyMood.IDLE || mood == BuddyMood.WAITING || mood == BuddyMood.SPEAKING)) {
            postInvalidateDelayed(40)
        }
    }

    private companion object {
        const val ACTION_PAT = 0x100101
        const val ACTION_POKE = 0x100102
    }
}
