package com.littlebuddy

import android.content.Intent
import android.widget.Button
import android.widget.LinearLayout

internal fun addAnimalEntry(content: LinearLayout) {
    val context = content.context
    content.addView(Button(context).apply {
        text = "玩猜动物"
        setOnClickListener { context.startActivity(Intent(context, AnimalActivity::class.java).putExtra("startGame", true)) }
    })
}
