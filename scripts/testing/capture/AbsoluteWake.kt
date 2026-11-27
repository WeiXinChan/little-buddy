package com.littlebuddy.v2
import android.content.res.AssetManager
import java.io.File
/** Controlled test boundary only; real ONNX/JNI is exercised by test-native-wake-origin.py. */
class AbsoluteWake(private val a:AssetManager,directory:File?,private val allowed:()->Boolean) {
 companion object { var initialized=0;var rearmed=0;var initializeHook:(Int)->Unit={};var rearmHook:()->Unit={} }
 private var delegate=com.littlebuddy.SherpaWake(a,allowed)
 fun initialize(){initialized++;initializeHook(initialized)}
 fun rearm(){rearmHook();rearmed++;delegate=com.littlebuddy.SherpaWake(a,allowed)}
 fun accept(s:ShortArray,n:Int)=delegate.accept(s,n)
 fun close()=delegate.close()
}
