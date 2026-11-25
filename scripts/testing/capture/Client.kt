package com.littlebuddy.v2
class VoiceClient {
 @Volatile var idleSerial=0L
 val inputSerial=0L
 val received=mutableListOf<ShortArray>()
 val wakes=mutableListOf<Long>()
 val order=mutableListOf<String>()
 fun frame(a:ShortArray,b:Boolean,c:Long){order+="frame";received+=a.copyOf()}
 fun quiet(){}
 fun wake(t:Long){order+="wake";wakes+=t}
}
