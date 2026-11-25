package com.littlebuddy.v2

import android.app.Activity
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.view.View
import android.widget.ImageView
import org.json.JSONArray
import java.security.MessageDigest
import java.util.concurrent.Executor

/** Only bundled, hash-verified PNGs. No URLs, server paths, cloud text or dynamic image claims. */
internal class AndroidImageRoute(private val activity: Activity, private val worker: Executor,
                                 private val image: ImageView) : ImagePort {
    private val gate: ImageGate<Bitmap> = ImageGate { activity.runOnUiThread { render() } }
    private fun render(): Unit = gate.render { bitmap ->
        image.setImageBitmap(bitmap); image.visibility = if (bitmap == null) View.GONE else View.VISIBLE
    }
    override fun bind(scope: ImageScope) = gate.bind(scope)
    override fun clear() = gate.clear()
    override fun acknowledged(player: String, stream: Int, segment: String, end: Long) =
        gate.acknowledged(player, stream, segment, end)
    override fun reveal(value: ImageReveal) { gate.reveal(value) }
    override fun ready(value: ImageReady) {
        val ticket = gate.prepare(value) ?: return
        try { worker.execute {
            val bitmap = runCatching {
                require(value.asset.id.matches(Regex("[a-z0-9-]{1,64}")))
                require(value.asset.width == 512 && value.asset.height == 512)
                val manifest = activity.assets.open("v2-default/manifest.json").use {
                    JSONArray(it.bufferedReader().readText())
                }
                require(manifest.length() == 60)
                val rows = (0 until manifest.length()).map { manifest.getJSONObject(it) }
                val entry = rows.single { it.getString("id") == value.asset.id }
                require(entry.getString("png_sha256") == value.asset.sha256 &&
                    entry.getInt("width") == 512 && entry.getInt("height") == 512)
                val bytes = activity.assets.open("v2-default/png/${value.asset.id}.png").use {
                    val data = it.readBytes(); require(data.size <= 1_048_576); data
                }
                val sha = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
                require(sha == value.asset.sha256)
                val options = BitmapFactory.Options().apply { inScaled = false }
                checkNotNull(BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)).also {
                    require(it.width == 512 && it.height == 512)
                }
            }.getOrNull()
            if (bitmap == null) gate.failed(ticket) else gate.loaded(ticket, bitmap)
        } } catch (_: java.util.concurrent.RejectedExecutionException) { gate.failed(ticket) }
    }
}
