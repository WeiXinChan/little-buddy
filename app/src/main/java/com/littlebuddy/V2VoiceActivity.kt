package com.littlebuddy

import android.Manifest
import android.app.Activity
import android.app.KeyguardManager
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.widget.TextView
import com.littlebuddy.v2.NativeEvidence
import com.littlebuddy.v2.RecorderProof
import com.littlebuddy.v2.PlayerProof
import com.littlebuddy.v2.Capture
import com.littlebuddy.v2.VoiceClient

/** Isolated V2 host. Endpoint/credential provisioner is deliberately absent until
 * reviewed; tests inject synthetic services. No existing V1 settings are read.
 */
class V2VoiceActivity : Activity() {
    private val audioThread = HandlerThread("v2-audio").apply { start() }
    private val owner = Handler(audioThread.looper)
    @Volatile internal var releaseState: String = "idle"; private set
    private var voice: VoiceClient? = null
    private var capture: Capture? = null
    private var releasedRecorder = RecorderProof()
    private var releasedPlayer = PlayerProof()
    internal fun observeNative(result: (NativeEvidence) -> Unit) { owner.post {
        result(NativeEvidence(capture?.nativeProof ?: releasedRecorder, voice?.nativeProof() ?: releasedPlayer))
    } }
    internal fun withVoice(action: (VoiceClient) -> Unit) { owner.post { voice?.let(action) } }
    private lateinit var label: TextView
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        label = TextView(this).apply { text = "瓦力 V2 · 待配置" }
        setContentView(label)
    }
    /** Called only by an authenticated V2 provisioner, not intent extras/voice. */
    internal fun startVoice(address: String, credential: String) {
        check(hasWindowFocus() && checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
        check(!getSystemService(KeyguardManager::class.java).isKeyguardLocked)
        owner.post {
            check(voice == null && capture == null)
            releaseState = "active"
            val client = VoiceClient(owner, { value -> runOnUiThread { label.text = value } }, {}, { _, _ -> }, { stopVoice() })
            voice = client
            client.connect(address, credential)
            capture = Capture(assets, owner, client) { stopVoice() }.also { it.start() }
        }
    }
    private fun stopVoice() { owner.post {
        voice?.close(); voice?.let { releasedPlayer = it.nativeProof() }
        if (voice?.quarantined != true) voice = null
        capture?.close(); capture?.let { releasedRecorder = it.nativeProof }
        // Failed capture release keeps the object, preventing new ownership.
        if (capture?.quarantined != true) capture = null
        releaseState = if (voice == null && capture == null) "released" else "quarantined"
    } }
    override fun onPause() { stopVoice(); super.onPause() }
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (!hasFocus) stopVoice()
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (grantResults.any { it != PackageManager.PERMISSION_GRANTED }) stopVoice()
    }
    override fun onDestroy() {
        stopVoice()
        owner.post { audioThread.quitSafely() }
        super.onDestroy()
    }
}
