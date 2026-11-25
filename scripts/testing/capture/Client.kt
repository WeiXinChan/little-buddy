package com.littlebuddy.v2
class VoiceClient {
 @Volatile var idleSerial=0L
 val inputSerial=0L
 val received=mutableListOf<ShortArray>()
 val wakes=mutableListOf<Long>()
 val order=mutableListOf<String>()
 val capturedTimes=mutableListOf<Long>()
 fun frame(a:ShortArray,b:Boolean,c:Long){order+="frame";capturedTimes+=c;received+=a.copyOf()}
 fun quiet(){}
 fun wake(t:Long){order+="wake";wakes+=t}
}

internal object CaptureMonotonic {fun nowMs()=android.os.SystemClock.uptimeMillis()}
