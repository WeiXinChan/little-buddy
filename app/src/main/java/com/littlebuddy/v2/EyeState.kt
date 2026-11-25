package com.littlebuddy.v2

internal data class EyeToken(val transport:Long,val page:Long)
internal enum class EyeMood { IDLE, CONNECTING, WAITING_WAKE, LISTENING, THINKING, PLAYING, WAITING_CHILD, FAULT }
/** Main-thread reducer. Server 'speaking' is not evidence of native playback. */
internal class EyeState {
    private var token:EyeToken?=null
    private var source=-1L
    private var recorder=false
    private var output=false
    private var request=""
    val mood:EyeMood get()=when {
        token==null->EyeMood.IDLE
        request !in setOf("", "compatibility", "wake", "listening", "thinking", "speaking",
            "waiting_complete","waiting_incomplete","waiting_thinking","clarify")->EyeMood.FAULT
        output->EyeMood.PLAYING
        request=="compatibility"->EyeMood.CONNECTING
        !recorder->EyeMood.IDLE
        request.startsWith("waiting_") || request=="clarify"->EyeMood.WAITING_CHILD
        request=="thinking" || request=="speaking"->EyeMood.THINKING
        request=="listening"->EyeMood.LISTENING
        else->EyeMood.WAITING_WAKE
    }
    fun activate(value:EyeToken){token=value;source=-1;recorder=false;output=false;request=""}
    fun revoke(){token=null;recorder=false;output=false}
    fun beginRecorder(value:EyeToken,id:Long){if(value==token){source=id;recorder=false}}
    fun recording(value:EyeToken,id:Long,active:Boolean){if(value==token && source==id)recorder=active}
    fun status(value:EyeToken,status:String){if(value==token)request=status}
    fun output(value:EyeToken,active:Boolean){if(value==token)output=active}
}
internal data class EyeShape(val rx:Float,val ry:Float,val lift:Float,val color:Int)
internal fun EyeMood.shape()=when(this) {
    EyeMood.IDLE->EyeShape(.065f,.045f,0f,0x3c7d8c)
    EyeMood.CONNECTING->EyeShape(.055f,.09f,0f,0x739cba)
    EyeMood.WAITING_WAKE->EyeShape(.065f,.16f,0f,0x62c4d8)
    EyeMood.LISTENING->EyeShape(.075f,.22f,-.015f,0x62dced)
    EyeMood.THINKING->EyeShape(.065f,.10f,-.04f,0xc5a5f4)
    EyeMood.PLAYING->EyeShape(.085f,.18f,0f,0xb3f5e3)
    EyeMood.WAITING_CHILD->EyeShape(.075f,.12f,.015f,0x8fd9cb)
    EyeMood.FAULT->EyeShape(.065f,.055f,.02f,0xf3b07a)
}

internal fun Completion.eyeStatus()=when(this) {
    Completion.COMPLETE->"waiting_complete"
    Completion.INCOMPLETE->"waiting_incomplete"
    Completion.THINKING->"waiting_thinking"
}
