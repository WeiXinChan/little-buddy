package com.littlebuddy.v2
import android.os.Handler
import android.media.AudioTrack
import android.widget.ImageView
import com.littlebuddy.v2.parent.ParentPlaybackSettings
import java.util.concurrent.*
fun main(args:Array<String>) {
    val owner=Handler();val worker=Executors.newSingleThreadExecutor();val image=ImageView()
    val route=AndroidImageRoute(android.app.Activity(),worker,image);val done=CountDownLatch(1)
    var failure:Throwable?=null;var phase=0;var earlyChecks=0
    lateinit var c:VoiceClient
    val monitor=object:Runnable {override fun run() {try {
        val tracks=AudioTrack.instances
        if(tracks.isNotEmpty()) {
            val first=tracks.first()
            if(first.plays==0) {check(image.bitmap==null){"image before full played ACK"};earlyChecks++}
            if(phase==0 && image.bitmap!=null && first.volume==0.5f) {
                check(earlyChecks>0 && first.plays==1);check(image.bitmap!!.width==512);phase=1
                c.frame(ShortArray(320),true);c.quiet()
            } else if(phase==1 && first.volume==0.4f) {
                check(first.plays==1 && first.playState==2){"volume resumed paused track"}
                check(image.bitmap==null);phase=2
            } else if(phase==2 && tracks.size>=2 && tracks[1].plays==1) {
                check(tracks[1].volume==0.4f){"new track lost temporary preference"}
                check(first.volume==0f);check(c.stopForManagement());route.clear();c.close()
                val actual=AndroidTrack(owner,ParentPlaybackSettings(60)){};val native=AudioTrack.instances.last()
                actual.mute();check(actual.setVolume(50));check(native.volume==0f && native.plays==0){"volume unmuted track"}
                actual.pause();check(actual.setVolume(40));check(native.volume==0f && native.plays==0)
                actual.stop();actual.release();check(image.bitmap==null)
                Thread.sleep(120);check(Handler.instances[1].pendingCallbacks()==0){"empty image route kept background timer"}
                println("MEDIA_TLS volume_pipeline=1 paused_no_resume=1 muted_no_unmute=1 next_track_reuse=1 png_ack_render=1 early_hidden=1 home_clear=1 empty_route_timer_stopped=1; native Android APIs are JVM ports")
                done.countDown();return
            }
        }
        owner.postDelayed(this,10)
    }catch(t:Throwable){failure=t;done.countDown()} } }
    c=VoiceClient(owner,{}, {route.inputChanged()}, {_,_->error("legacy reveal")},
        failed={failure=AssertionError("media client failed");done.countDown()},images=route,
        playbackSettings=ParentPlaybackSettings(60),requiredContract=ReleaseCompatibility.CONTRACT,
        ready={c.wake();c.frame(ShortArray(320),true);c.quiet();owner.post(monitor)})
    owner.post {c.connect(args[0],"A".repeat(32))}
    val completed=done.await(12,TimeUnit.SECONDS)
    owner.post {c.close();route.clear()};worker.shutdownNow()
    if(!completed)failure=AssertionError("media pipeline incomplete phase=$phase")
    failure?.let{it.printStackTrace();kotlin.system.exitProcess(1)}
    kotlin.system.exitProcess(0)
}
