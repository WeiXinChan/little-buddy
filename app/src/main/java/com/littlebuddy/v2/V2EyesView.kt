package com.littlebuddy.v2

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.view.MotionEvent
import android.view.View

/** Daily surface contains only two eyes. Hidden corner fallback opens verification, never a grant. */
internal class V2EyesView(context: Context, private val requestManagement: () -> Unit) : View(context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(98, 220, 237) }
    var onLocalHelp: () -> Unit = {}
    private var helpHold = false
    private var holding = false
    private val held = Runnable { if (holding && hasWindowFocus()) {
        holding = false
        if (helpHold) onLocalHelp() else requestManagement()
    } }
    init { setBackgroundColor(Color.BLACK); contentDescription = "瓦力的两只眼睛。长按眼睛查看本机帮助，长按右下角进入家长验证。"; isSaveEnabled = false }
    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val rx = width * .065f; val ry = height * .20f; val cy = height * .49f
        for (cx in floatArrayOf(width * .36f, width * .64f)) canvas.drawOval(cx - rx, cy - ry, cx + rx, cy + ry, paint)
    }
    override fun onTouchEvent(event: MotionEvent): Boolean {
        val corner = event.x >= width * .90f && event.y >= height * .85f
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                holding = true; helpHold = !corner
                postDelayed(held, 900)
            }
            MotionEvent.ACTION_MOVE -> if ((!helpHold && !corner) || event.x !in 0f..width.toFloat() || event.y !in 0f..height.toFloat()) { holding = false; removeCallbacks(held) }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> { holding = false; removeCallbacks(held) }
        }
        return true
    }
    override fun onDetachedFromWindow() { holding = false; removeCallbacks(held); super.onDetachedFromWindow() }
}
