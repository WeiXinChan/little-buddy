package com.littlebuddy.v2
import android.content.res.AssetManager
import java.io.File
/** Controlled test boundary only; real ONNX/JNI is exercised by test-native-wake-origin.py. */
class AbsoluteWake(a:AssetManager,directory:File?,allowed:()->Boolean) {
 private val delegate=com.littlebuddy.SherpaWake(a,allowed)
 fun initialize(){}
 fun accept(s:ShortArray,n:Int)=delegate.accept(s,n)
 fun close()=delegate.close()
}
