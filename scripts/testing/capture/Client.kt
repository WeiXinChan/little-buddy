package com.littlebuddy.v2
class VoiceClient {
 @Volatile var idleSerial=0L
 @Volatile var inputSerial=0L
 val received=mutableListOf<ShortArray>()
 val wakes=mutableListOf<Long>()
 val order=mutableListOf<String>()
 val capturedTimes=mutableListOf<Long>()
 fun frame(a:ShortArray,b:Boolean,c:Long){order+="frame";capturedTimes+=c;received+=a.copyOf()}
 fun beginCaptureImport(t:Long){}
 fun endCaptureImport(){}
 fun quiet(){}
 fun wake(t:Long,wakeTailFrame:Long=-1,captureFrame:Long=-1,wakeRelativeMs:Long=-1){order+="wake";wakes+=t}
}

internal object CaptureMonotonic {fun nowMs()=android.os.SystemClock.uptimeMillis()}
