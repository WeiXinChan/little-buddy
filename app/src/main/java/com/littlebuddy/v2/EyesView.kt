package com.littlebuddy.v2

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.os.SystemClock
import android.view.View
import kotlin.math.sin

/** Actual default V2 surface; no text, controls or debug affordances. */
internal class EyesView(context: Context) : View(context) {
    var mood = EyeMood.WAKE
        set(value) { field = value; invalidate() }
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private var image: Bitmap? = null
    private var imageUntil = 0L
    internal val showingImage get() = image != null && SystemClock.uptimeMillis() < imageUntil
    fun clearImage() { image = null; invalidate() }
    fun showImage(bitmap: Bitmap, durationMs: Long = 4000) {
        require(durationMs in 1..8000)
        image = bitmap; imageUntil = SystemClock.uptimeMillis() + durationMs; invalidate()
    }
    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        canvas.drawColor(Color.rgb(7, 14, 29))
        val now = SystemClock.uptimeMillis()
        image?.let {
            if (now < imageUntil) {
                val scale = minOf(width.toFloat()/it.width, height.toFloat()/it.height)
                val w = it.width*scale; val h = it.height*scale
                canvas.drawBitmap(it, null, RectF((width-w)/2, (height-h)/2, (width+w)/2, (height+h)/2), paint)
                postInvalidateDelayed(32); return
            }
            image = null
        }
        val unit = minOf(width/2.45f, height/1.55f)
        val horizontal = width / 2.12f
        val vertical = height / 1.16f
        val pulse = sin(now/260.0).toFloat()
        val eyeWidth = horizontal*.91f
        val eyeHeight = vertical * when(mood) {
            EyeMood.WAKE -> .78f
            EyeMood.LISTENING -> .95f
            EyeMood.THINKING -> .64f
            EyeMood.SPEAKING -> .77f + .055f*pulse
            EyeMood.WAITING -> .64f
            EyeMood.FAILURE -> .38f
        }
        val color = when(mood) {
            EyeMood.WAKE -> Color.rgb(98, 153, 182)
            EyeMood.THINKING -> Color.rgb(169, 150, 244)
            EyeMood.FAILURE -> Color.rgb(245, 184, 103)
            else -> Color.rgb(117, 229, 242)
        }
        for (side in listOf(-1, 1)) {
            val x = width/2f + side*horizontal*.54f
            val y = height/2f + if (mood == EyeMood.THINKING) -unit*.09f else 0f
            paint.color = color
            canvas.drawRoundRect(RectF(x-eyeWidth/2, y-eyeHeight/2, x+eyeWidth/2, y+eyeHeight/2), eyeWidth*.48f, eyeHeight*.48f, paint)
            if (mood != EyeMood.FAILURE) {
                paint.color = Color.rgb(9, 29, 46)
                val dx = if (mood == EyeMood.THINKING) unit*.1f else 0f
                canvas.drawOval(RectF(x-unit*.13f+dx, y-unit*.17f, x+unit*.13f+dx, y+unit*.17f), paint)
                paint.color = Color.WHITE
                canvas.drawCircle(x-unit*.045f+dx, y-unit*.065f, unit*.036f, paint)
            }
        }
        if (mood == EyeMood.THINKING || mood == EyeMood.SPEAKING) postInvalidateDelayed(40)
    }
}
