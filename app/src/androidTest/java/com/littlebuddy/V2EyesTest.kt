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
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
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
        inst.waitForIdleSync()
        val bitmap = checkNotNull(inst.uiAutomation.takeScreenshot())
        val out = File(inst.targetContext.filesDir, "m06").apply { mkdirs() }
        File(out,"$name.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) }
        assertTrue("actual screenshot must be landscape: ${bitmap.width}x${bitmap.height}",bitmap.width > bitmap.height)
    }
    private fun stableDefault(activity: V2VoiceActivity) {
        val first=activity.eyesFrame; val deadline=SystemClock.elapsedRealtime()+5000
        while(SystemClock.elapsedRealtime()<deadline) {
            main { activity.requestEyesFrame() }
            inst.waitForIdleSync()
            if(activity.resumed && activity.hasWindowFocus() && activity.eyesFrame>=first+2) {
                val bitmap=checkNotNull(inst.uiAutomation.takeScreenshot())
                val dark=Color.rgb(7,14,29)
                val stable=bitmap.getPixel(bitmap.width/2,bitmap.height/2)==dark && bitmap.getPixel(bitmap.width/2,32)==dark
                bitmap.recycle()
                if(stable)return
            }
            Thread.sleep(16)
        }
        throw AssertionError("default EyesView stable rendered frames missing: "+diagnostics(activity))
    }
    private fun saveTimeline(activity: V2VoiceActivity,name: String) {
        File(inst.targetContext.filesDir,"m06").mkdirs()
        File(inst.targetContext.filesDir,"m06/$name.json").writeText(activity.timelineJson())
    }
    private fun proof(activity: V2VoiceActivity): NativeEvidence {
        val latch = CountDownLatch(1); val result = AtomicReference<NativeEvidence>()
        activity.observeNative { result.set(it); latch.countDown() }
        check(latch.await(3,TimeUnit.SECONDS)); return result.get()
    }
    private fun diagnostics(activity: V2VoiceActivity): String {
        val latch=CountDownLatch(1); val result=AtomicReference<String>()
        activity.observeDiagnostics { result.set(it); latch.countDown() }
        return if (latch.await(3,TimeUnit.SECONDS)) result.get() else "OWNER_UNRESPONSIVE"
    }
    private fun resumedHost(): V2VoiceActivity? {
        var host: V2VoiceActivity? = null
        main { host=ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED).filterIsInstance<V2VoiceActivity>().singleOrNull() }
        return host
    }
    private fun readyLocalHost(exclude: V2VoiceActivity? = null): V2VoiceActivity? {
        val deadline=SystemClock.elapsedRealtime()+15000
        while(SystemClock.elapsedRealtime()<deadline) {
            val host=resumedHost()
            if(host != null && host !== exclude && host.hasWindowFocus()) {
                val recorder=proof(host).recorder
                if(recorder.started && recorder.recording && recorder.frames>0) return host
            }
            Thread.sleep(50)
        }
        return null
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
            stableDefault(activity); shot("01-default-landscape")
            val deadline = SystemClock.elapsedRealtime()+15000
            while (proof(activity).recorder.frames == 0L && SystemClock.elapsedRealtime() < deadline) Thread.sleep(50)
            val diagnosis = diagnostics(activity)
            File(context.filesDir,"m06/diagnostics.txt").writeText(diagnosis)
            println("M06_DIAGNOSTICS $diagnosis")
            val recorder = proof(activity).recorder
            assertTrue("local command recorder must really run: $diagnosis", recorder.started && recorder.recording && recorder.frames > 0)
            assertEquals(EyeMood.WAKE, activity.currentMood)
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
            assertNull(client.nativeProof().binding)
            assertEquals(StopResult(true,true),client.nativeProof().stop)
            wire("audio","player" to playerName,"stream" to 1,"segment" to "late", "start" to 2400,"end" to 2640,"pcm" to android.util.Base64.encodeToString(ByteArray(480),android.util.Base64.NO_WRAP))
            assertNull(client.nativeProof().binding)
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
            assertTrue("HOME precondition real recorder READ",before.started && before.recording && before.frames>0)
            activity.mark("HOME_COMMAND_BEGIN")
            inst.uiAutomation.executeShellCommand("input keyevent KEYCODE_HOME").use {
                java.io.FileInputStream(it.fileDescriptor).readBytes()
            }
            activity.mark("HOME_COMMAND_COMPLETE")
            val homeDeadline=SystemClock.elapsedRealtime()+2000
            while((activity.resumed || activity.hasWindowFocus()) && SystemClock.elapsedRealtime()<homeDeadline)Thread.sleep(20)
            val top=inst.uiAutomation.executeShellCommand("dumpsys activity activities").use {
                java.io.FileInputStream(it.fileDescriptor).bufferedReader().readLines()
                    .filter { it.contains("topResumedActivity") || it.contains("mResumedActivity") }.joinToString("\n")
            }
            File(context.filesDir,"m06/home-top.txt").writeText(top)
            activity.mark("HOME_STATE_OBSERVED")
            saveTimeline(activity,"home-before-stop-check")
            val homePackage=context.packageManager.resolveActivity(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME),android.content.pm.PackageManager.MATCH_DEFAULT_ONLY)?.activityInfo?.packageName
            val resolved=inst.uiAutomation.executeShellCommand("cmd package resolve-activity --brief --user 0 -a android.intent.action.MAIN -c android.intent.category.HOME").use {java.io.FileInputStream(it.fileDescriptor).bufferedReader().readText().trim()}
            File(context.filesDir,"m06/home-resolution.txt").writeText("appVisible=$homePackage shell=$resolved")
            val component=resolved.lineSequence().lastOrNull{it.contains('/')}
            assertTrue("HOME must show resolved desktop: $resolved got $top",component!=null && top.contains(component))
            assertFalse("HOME must actually pause old Host: $top",activity.resumed)
            assertFalse("HOME must remove old Host focus: $top",activity.hasWindowFocus())
            val stopDeadline=SystemClock.elapsedRealtime()+1000
            var stopped=activity.immediateRecorder()
            while(!(stopped.stopped && stopped.released && !stopped.recording) && SystemClock.elapsedRealtime()<stopDeadline) {
                Thread.sleep(10); stopped=activity.immediateRecorder()
            }
            activity.mark("HOME_STOP_BUDGET_END")
            saveTimeline(activity,"home-stop-result")
            File(context.filesDir,"m06/home-proof.txt").writeText("before=$before after=$stopped "+activity.captureWorkerEvidence()+" "+diagnostics(activity))
            assertEquals(before.session,stopped.session)
            assertTrue("old native stop/release budget failed: $stopped",stopped.stopped && stopped.released && !stopped.recording)
            Thread.sleep(100); assertEquals(stopped.frames,activity.immediateRecorder().frames)
            context.startActivity(Intent(context,V2VoiceActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))
            val returned=readyLocalHost()
            val returnedDiagnostics=diagnostics(returned ?: resumedHost() ?: activity)
            File(context.filesDir,"m06/home-return-diagnostics.txt").writeText(returnedDiagnostics)
            shot("15-home-return-wake")
            assertNotNull("resumed/focused new recorder READ required: $returnedDiagnostics",returned)
            val host=checkNotNull(returned)
            assertEquals("local_kws",host.releaseState)
            assertNotEquals("new KWS must not reuse old native recorder session",before.session,proof(host).recorder.session)
            assertEquals(EyeMood.WAKE,host.currentMood)
            val noUpload=CountDownLatch(1)
            host.withVoice { local ->
                assertFalse(local.connectionActive); assertEquals(0L,local.sentPackets); noUpload.countDown()
            }
            assertTrue("new local KWS/zero upload proof missing: $returnedDiagnostics",noUpload.await(3,TimeUnit.SECONDS))
            main { host.recreate() }
            val restarted=readyLocalHost(host)
            assertNotNull("recreate must return to focused local KWS READ",restarted)
            assertEquals(EyeMood.WAKE,checkNotNull(restarted).currentMood)
            stableDefault(checkNotNull(restarted)); shot("16-restart-default")
        } finally { val current=resumedHost(); main { client.close(); current?.finish(); if(!activity.isFinishing) activity.finish() } }
    }
}
