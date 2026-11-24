package com.littlebuddy

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.ViewGroup
import android.widget.Button
import androidx.test.platform.app.InstrumentationRegistry
import com.littlebuddy.v2.*
import org.json.JSONObject
import okhttp3.Request
import okhttp3.WebSocket
import okio.ByteString
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/** Real emulator windows; synthetic wire events traverse production receive/playback. */
class V2EyesTest {
    private class WireSocket : WebSocket {
        val messages = mutableListOf<String>()
        override fun request() = Request.Builder().url("wss://synthetic.invalid/v2/voice").build()
        override fun queueSize() = 0L
        override fun send(text: String): Boolean { messages += text; return true }
        override fun send(bytes: ByteString) = false
        override fun close(code: Int, reason: String?) = true
        override fun cancel() {}
        fun inputs() = messages.count { JSONObject(it).getString("type") == "input" }
    }
    private val inst get() = InstrumentationRegistry.getInstrumentation()
    private fun main(action: () -> Unit) = inst.runOnMainSync(action)
    private fun shot(name: String) {
        inst.waitForIdleSync(); Thread.sleep(100)
        val bitmap = checkNotNull(inst.uiAutomation.takeScreenshot())
        val out = File(inst.targetContext.filesDir, "m06").apply { mkdirs() }
        File(out,"$name.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) }
    }
    private fun proof(activity: V2VoiceActivity): NativeEvidence {
        val latch = CountDownLatch(1); val result = AtomicReference<NativeEvidence>()
        activity.observeNative { result.set(it); latch.countDown() }
        check(latch.await(3,TimeUnit.SECONDS)); return result.get()
    }
    @Test fun realWindowAndProductionWireStates() {
        val context = inst.targetContext
        val activity = inst.startActivitySync(Intent(context,V2VoiceActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as V2VoiceActivity
        val client = VoiceClient(Handler(Looper.getMainLooper()), activity::handleStatus, activity::hideImage, activity::revealImage)
        val receive = client.javaClass.getDeclaredMethod("receive",String::class.java).apply { isAccessible = true }
        fun wire(type: String, vararg fields: Pair<String,Any>) { main {
            val epoch = client.javaClass.getDeclaredField("epoch").apply { isAccessible = true }.getLong(client)
            val event = JSONObject().put("v",2).put("epoch",epoch).put("type",type)
            fields.forEach { event.put(it.first,it.second) }
            receive.invoke(client,event.toString())
        } }
        try {
            val deadline = SystemClock.elapsedRealtime()+15000
            while (proof(activity).recorder.frames == 0L && SystemClock.elapsedRealtime() < deadline) Thread.sleep(50)
            assertTrue("local command recorder must really run", proof(activity).recorder.recording)
            assertEquals(EyeMood.WAKE, activity.currentMood); shot("01-default-landscape")
            main { client.wake() } // Disconnected wake reports failure, never comprehension.
            shot("02-failure")
            val wireSocket = WireSocket()
            main {
                client.javaClass.getDeclaredField("socket").apply { isAccessible = true }.set(client,wireSocket)
                client.javaClass.getDeclaredField("active").apply { isAccessible = true }.setBoolean(client,true)
                client.wake(); client.frame(ShortArray(320){42},true)
            }
            assertEquals(1,wireSocket.inputs()); shot("03-listening")
            wire("thinking_wait"); shot("04-thinking")
            main { client.quiet() }; shot("05-waiting")
            wire("open","revision" to 1)
            val field = client.javaClass.getDeclaredField("playerName").apply { isAccessible = true }
            val playerName = field.get(client) as String
            wire("bound","player" to playerName,"identity" to JSONObject(),"stream" to 1)
            val playerField = client.javaClass.getDeclaredField("player").apply { isAccessible = true }
            val player = playerField.get(client) as Playback
            wire("audio","player" to playerName,"stream" to 1,"segment" to "synthetic",
                "start" to 0,"end" to 2400,"pcm" to android.util.Base64.encodeToString(ByteArray(4800),android.util.Base64.NO_WRAP))
            repeat(30) { main { player.tick() }; Thread.sleep(20) }
            assertTrue("real AudioTrack head must advance",client.nativeProof().observedHead > 0)
            shot("06-speaking-native-head")
            val sample = Bitmap.createBitmap(360,240,Bitmap.Config.ARGB_8888).apply { eraseColor(Color.rgb(100,180,100)) }
            main { activity.pictureResolver = { if (it == "synthetic-patch") sample else null } }
            wire("reveal","effect" to "synthetic-patch","topic" to 1)
            wire("reply_end","head" to 2400,"public_facts" to 1)
            assertTrue(activity.showingImage); shot("07-image-survives-listening")
            main { activity.displayEvent("speaking") }; assertTrue(activity.showingImage); shot("08-image-survives-speaking")
            Thread.sleep(4100); assertFalse(activity.showingImage); shot("09-image-expired-eyes")
            wire("reveal","effect" to "synthetic-patch","topic" to 0)
            assertFalse(activity.showingImage); shot("10-old-topic-rejected")
            wire("reveal","effect" to "synthetic-patch","topic" to 2)
            assertTrue(activity.showingImage)
            main { client.management(true); activity.manage(true) }
            val uploadsBeforeManagement = wireSocket.inputs()
            main {
                val pcm = ShortArray(320){42}; client.frame(pcm,true)
                assertTrue(pcm.all { it == 0.toShort() })
            }
            assertEquals(uploadsBeforeManagement,wireSocket.inputs())
            wire("reply_end","head" to 2400,"public_facts" to 1)
            wire("reveal","effect" to "synthetic-patch","topic" to 2)
            assertTrue(activity.isManaging); assertFalse(activity.showingImage); shot("11-locked-management-late-output")
            main {
                client.management(false); activity.manage(false)
                client.frame(ShortArray(320){42},true)
                receive.invoke(client,JSONObject().put("v",2).put("epoch",0).put("type","reply_end").put("head",2400).put("public_facts",1).toString())
            }
            assertFalse(client.isAwake); assertEquals(uploadsBeforeManagement,wireSocket.inputs()); assertEquals(EyeMood.WAKE, activity.currentMood); shot("12-exit-wake")
            // Production management wire routing with no provisioned credentials.
            wire("management")
            inst.waitForIdleSync(); Thread.sleep(300)
            shot("13-unconfigured-voice-management-route")
            main {
                val panel = activity.findViewById<ViewGroup>(android.R.id.content).getChildAt(0) as ViewGroup
                val cancel = (0 until panel.childCount).map { panel.getChildAt(it) }.filterIsInstance<Button>().single()
                cancel.performClick()
            }
            Thread.sleep(300); shot("14-button-cancel-wake")
            val before = proof(activity).recorder
            inst.uiAutomation.executeShellCommand("input keyevent KEYCODE_HOME").use {
                java.io.FileInputStream(it.fileDescriptor).readBytes()
            }
            Thread.sleep(600)
            val stopped = proof(activity).recorder
            assertEquals(before.session, stopped.session)
            assertTrue(stopped.stopped && stopped.released && !stopped.recording)
            context.startActivity(Intent(context,V2VoiceActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))
            Thread.sleep(500); shot("15-home-return-wake")
            assertEquals(EyeMood.WAKE, activity.currentMood)
            val noUpload = CountDownLatch(1)
            activity.withVoice { local ->
                assertFalse(local.connectionActive); assertEquals(0L, local.sentPackets); noUpload.countDown()
            }
            assertTrue(noUpload.await(3,TimeUnit.SECONDS))
            main { activity.recreate() }; Thread.sleep(500); shot("16-restart-default")
        } finally { main { client.close(); activity.finish() } }
    }
}
