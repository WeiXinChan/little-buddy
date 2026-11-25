package com.littlebuddy
import android.content.res.AssetManager
import java.util.concurrent.CountDownLatch
class SherpaWake(a:AssetManager,private val allowed:()->Boolean={true}) {
 companion object { @Volatile var detectAfter=21;@Volatile var blockClose:CountDownLatch?=null }
 var reads=0
 fun accept(s:ShortArray,n:Int):Long? {reads++;return if(reads>=detectAfter && allowed())0L else null}
 fun close(){blockClose?.await()}
}
class SpeechDetector(a:Int,initialFloor:Double) {val detectedSpeechInRead=true;fun accept(a:ShortArray,n:Int) {}}
