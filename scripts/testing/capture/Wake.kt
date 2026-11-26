package com.littlebuddy
import android.content.res.AssetManager
import java.util.concurrent.CountDownLatch
class SherpaWake(a:AssetManager,private val allowed:()->Boolean={true}) {
 companion object { @Volatile var detectAfter=21;@Volatile var blockClose:CountDownLatch?=null;@Volatile var delayMs=0L;var delayForRead:(Int)->Long={delayMs};var observe:(ShortArray,Int)->Unit={_,_->} }
 var reads=0
 fun accept(s:ShortArray,n:Int):Long? {observe(s,n);reads++;val delay=delayForRead(reads);if(delay>0)Thread.sleep(delay);return if(reads>=detectAfter && allowed())0L else null}
 fun close(){blockClose?.await()}
}
class SpeechDetector(a:Int,initialFloor:Double) {val detectedSpeechInRead=true;fun accept(a:ShortArray,n:Int) {}}
