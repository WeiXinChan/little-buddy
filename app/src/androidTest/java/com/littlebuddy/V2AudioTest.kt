package com.littlebuddy

import android.Manifest
import android.app.KeyguardManager
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.PowerManager
import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import com.littlebuddy.v2.*
import org.junit.Assert.*
import org.junit.Assume.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.sin

class V2AudioTest {
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private val args get() = InstrumentationRegistry.getArguments()
    private val context get() = instrumentation.targetContext
    private fun fixture(): Pair<String,String> {
        val address=args.getString("v2Address"); val token=args.getString("v2FixtureToken")
        assumeNotNull(address,token)
        return Pair(checkNotNull(address),checkNotNull(token))
    }
    private fun await(message: String, condition: () -> Boolean) {
        val deadline=SystemClock.elapsedRealtime()+5000
        while (!condition() && SystemClock.elapsedRealtime()<deadline) Thread.sleep(20)
        assertTrue(message,condition())
    }
    private fun shell(vararg command: String) {
        instrumentation.uiAutomation.executeShellCommand(command.joinToString(" ")).use {
            java.io.FileInputStream(it.fileDescriptor).readBytes() // Wait for actual shell completion.
        }
    }
    private fun launch(): V2VoiceActivity {
        assertEquals("com.littlebuddy.sim.v2",context.packageName)
        val intent=Intent(context,V2VoiceActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        val activity=instrumentation.startActivitySync(intent) as V2VoiceActivity
        await("activity focus") { activity.hasWindowFocus() }
        return activity
    }
    private fun observe(activity: V2VoiceActivity): NativeEvidence {
        val ready=CountDownLatch(1); val result=AtomicReference<NativeEvidence>()
        activity.observeNative { result.set(it); ready.countDown() }
        check(ready.await(2,TimeUnit.SECONDS))
        return result.get()
    }
    private fun running(activity: V2VoiceActivity): NativeEvidence {
        var latest=observe(activity)
        await("real AudioRecord RECORDING/read frames and bound AudioTrack head progress required") {
            latest=observe(activity)
            runCatching { latest.requireRunning() }.isSuccess
        }
        return latest
    }
    private fun start(activity: V2VoiceActivity, address: String, token: String): NativeEvidence {
        instrumentation.runOnMainSync { activity.startVoice(address,token) }
        // Synthetic intent traverses the production transport; physical recorder
        // independently must report RECORDING and nonzero reads before readiness.
        activity.withVoice { client -> client.wake(); client.frame(ShortArray(320){300},true); client.quiet() }
        return running(activity)
    }
    private fun released(activity: V2VoiceActivity, before: NativeEvidence): NativeEvidence {
        var result=observe(activity)
        await("native stop/release confirmation for the same recorder and player") {
            result=observe(activity)
            runCatching { result.requireReleased(before) }.isSuccess
        }
        return result
    }
    private fun assertNoAutomaticResume(activity: V2VoiceActivity, before: NativeEvidence) {
        val closed=released(activity,before)
        Thread.sleep(300)
        val after=observe(activity)
        after.requireReleased(before)
        assertEquals(closed.recorder.frames,after.recorder.frames)
        assertEquals(closed.player.observedHead,after.player.observedHead)
    }
    private fun finish(activity: V2VoiceActivity) { instrumentation.runOnMainSync { activity.finish() } }

    @Test fun nativeTrackAckAndStopReleaseUseProductionPump() {
        val thread=HandlerThread("v2-native-test").apply { start() }; val handler=Handler(thread.looper)
        val finished=CountDownLatch(1); val failure=AtomicReference<Throwable?>()
        val binding=Binding(1,"instrumented-native",1); var player: Playback?=null
        handler.post {
            try {
                player=Playback({ AndroidTrack(handler) { error("route changed") } },SystemClock::elapsedRealtime) { ack ->
                    if (ack.head>=2400) {
                        assertEquals(StopResult(true,true),checkNotNull(player).stop())
                        assertFalse(checkNotNull(player).enqueue(AudioPacket(binding,"late",2400,2401,shortArrayOf(2))))
                        finished.countDown()
                    }
                }
                checkNotNull(player).bind(binding)
                val tone=ShortArray(2400){(1200*sin(2*Math.PI*440*it/24000)).toInt().toShort()}
                checkNotNull(player).enqueue(AudioPacket(binding,"tone",0,2400,tone))
            } catch (t:Throwable) { failure.set(t); finished.countDown() }
        }
        val pump=object:Runnable { override fun run() {
            try { player?.tick() } catch(t:Throwable) { failure.set(t); finished.countDown() }
            if(finished.count>0) handler.postDelayed(this,10)
        } }
        handler.post(pump)
        try { assertTrue(finished.await(5,TimeUnit.SECONDS)); failure.get()?.let { throw it } }
        finally {
            val done=CountDownLatch(1)
            handler.post { player?.stop(); done.countDown(); thread.quitSafely() }
            assertTrue(done.await(1,TimeUnit.SECONDS)); thread.join(1000)
        }
    }

    @Test fun backgroundReleasesRecorderAndPlayerWithoutAutomaticResume() {
        val (address,token)=fixture(); shell("pm","grant",context.packageName,Manifest.permission.RECORD_AUDIO)
        val activity=launch()
        try {
            val before=start(activity,address,token)
            context.startActivity(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            released(activity,before)
            context.startActivity(Intent(context,V2VoiceActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            await("return foreground") { activity.hasWindowFocus() }
            assertNoAutomaticResume(activity,before)
            val recovered=start(activity,address,token)
            assertNotEquals(before.player.binding,recovered.player.binding)
        } finally { finish(activity) }
    }

    @Test fun startupFailureCannotPassNativeReadiness() {
        fixture(); shell("pm","grant",context.packageName,Manifest.permission.RECORD_AUDIO)
        val activity=launch()
        try {
            instrumentation.runOnMainSync { activity.startVoice("wss://localhost:1/v2/voice","SyntheticOnly".repeat(4)) }
            Thread.sleep(500)
            assertTrue("failed startup must be rejected by the same readiness oracle",
                runCatching { observe(activity).requireRunning() }.isFailure)
        } finally { finish(activity) }
    }

    @Test fun lockScreenReleasesAndUnlockRequiresExplicitNewConnection() {
        val (address,token)=fixture()
        val keyguard=context.getSystemService(KeyguardManager::class.java)
        // Never add/change credentials or ask the user to unlock. A secure device
        // needs its already-authorized automation unlock path; otherwise NOT_RUN.
        assumeFalse("secure unlock automation unavailable: do not alter device credentials",keyguard.isDeviceSecure)
        shell("pm","grant",context.packageName,Manifest.permission.RECORD_AUDIO)
        val activity=launch()
        try {
            val before=start(activity,address,token)
            shell("input","keyevent","223")
            await("actual system lock and display off") {
                keyguard.isKeyguardLocked && !context.getSystemService(PowerManager::class.java).isInteractive
            }
            released(activity,before)
            shell("input","keyevent","224"); shell("wm","dismiss-keyguard")
            context.startActivity(Intent(context,V2VoiceActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            await("unlocked focus") { !keyguard.isKeyguardLocked && activity.hasWindowFocus() }
            assertNoAutomaticResume(activity,before)
            val recovered=start(activity,address,token)
            assertNotEquals(before.player.binding,recovered.player.binding)
        } finally { shell("input","keyevent","224"); shell("wm","dismiss-keyguard"); finish(activity) }
    }

    private fun roundTrip(suppressFinalAck: Boolean) {
        val (address,token)=fixture()
        val thread=HandlerThread("v2-wire-test").apply{start()}; val owner=Handler(thread.looper)
        val localHead=CountDownLatch(1); val confirmed=CountDownLatch(1); val failed=AtomicReference<String?>()
        var client:VoiceClient?=null
        owner.post {
            client=VoiceClient(owner,{}, {}, {_,_->}, { failed.set("client failure"); confirmed.countDown() },
                observed={if(it.head>=12000)localHead.countDown()},
                completed={head,facts-> if(head>=12000 && facts>0)confirmed.countDown()},
                allowAck={ !suppressFinalAck || it.head<12000 })
            checkNotNull(client).connect(address,token)
            owner.postDelayed({ client?.wake(); client?.frame(ShortArray(320){300},true); client?.quiet() },300)
        }
        try {
            assertTrue("native head must actually reach the final frame",localHead.await(8,TimeUnit.SECONDS))
            if(suppressFinalAck) {
                assertFalse("local head is insufficient; suppressed final ACK must fail server completion",confirmed.await(1500,TimeUnit.MILLISECONDS))
            } else assertTrue("server must consume final ACK and return played fact/reply_end receipt",confirmed.await(3,TimeUnit.SECONDS))
            assertNull(failed.get())
        } finally {
            val done=CountDownLatch(1); owner.post{ client?.close(); done.countDown(); thread.quitSafely() }
            assertTrue(done.await(1,TimeUnit.SECONDS)); thread.join(1000)
        }
    }
    @Test fun realTlsWebsocketFeedsRealTrackAndAckReturnsToBackend()=roundTrip(false)
    @Test fun suppressedFinalAckCannotPassRoundTripOracle()=roundTrip(true)

    @Test fun permissionRevocationPreparation() {
        assumeTrue(args.getString("v2PermissionPhase")=="prepare")
        val(address,token)=fixture(); val activity=launch()
        try {
            val before=start(activity,address,token); before.requireRunning()
            instrumentation.sendStatus(7,Bundle().apply {
                putString("v2_phase","V2_NATIVE_READY_FOR_REVOKE")
                putString("v2_player",before.player.binding!!.player)
                putLong("v2_head",before.player.observedHead); putLong("v2_reads",before.recorder.frames)
                putInt("v2_pid",android.os.Process.myPid())
            })
            Thread.sleep(30000)
            fail("host must actually revoke permission and observe OS teardown; no simulated callback")
        } finally { finish(activity) }
    }
    @Test fun permissionDeniedStartupDoesNotRecord() {
        assumeTrue(args.getString("v2PermissionPhase")=="denied")
        assertEquals(PackageManager.PERMISSION_DENIED,context.checkSelfPermission(Manifest.permission.RECORD_AUDIO))
        val activity=launch()
        try {
            val(address,token)=fixture(); var denied=false
            instrumentation.runOnMainSync { try {activity.startVoice(address,token)}catch(_:IllegalStateException){denied=true} }
            assertTrue(denied)
            assertTrue(runCatching {observe(activity).requireRunning()}.isFailure)
        } finally {finish(activity)}
    }
    @Test fun permissionRestoredRequiresExplicitNewConnection() {
        assumeTrue(args.getString("v2PermissionPhase")=="restored")
        val(address,token)=fixture(); val activity=launch()
        try {
            assertTrue("grant/relaunch must not auto-record",runCatching{observe(activity).requireRunning()}.isFailure)
            val running=start(activity,address,token)
            assertNotEquals(args.getString("v2PreviousPlayer"),running.player.binding!!.player)
            instrumentation.runOnMainSync {activity.finish()}
            // onDestroy quits the owner; HOME is used for the same-object native
            // release assertions in the dedicated HOME case. Here a new connection
            // and native recording/head prove recovery after actual process death.
        } finally {if(!activity.isFinishing)finish(activity)}
    }
}
