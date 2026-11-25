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
    private var mood=EyeMood.IDLE
    fun show(value:EyeMood) {
        if(mood==value)return
        mood=value
        contentDescription=when(value) {
            EyeMood.IDLE->"瓦力暂未收音"
            EyeMood.CONNECTING->"瓦力正在核对连接"
            EyeMood.WAITING_WAKE->"瓦力在本机等待唤醒"
            EyeMood.LISTENING->"瓦力正在听"
            EyeMood.THINKING->"瓦力正在想"
            EyeMood.PLAYING->"瓦力正在播放"
            EyeMood.WAITING_CHILD->"瓦力在等你继续"
            EyeMood.FAULT->"瓦力暂时遇到问题，收音或回答可能已暂停"
        }
        invalidate()
    }
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
        val shape=mood.shape();paint.color=0xff000000.toInt() or shape.color
        val rx=width*shape.rx;val ry=height*shape.ry;val cy=height*(.49f+shape.lift)
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
