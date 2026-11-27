package com.littlebuddy.v2

/** Wire strings never become diagnostic text or retry instructions. */
internal enum class ServerFailure(val localCode:String) {
    TIMEOUT("server_timeout"), QUOTA("server_quota"), VOICE("server_voice"),
    SAFETY("server_safety"), AUTH("server_auth"), UNAVAILABLE("server_unavailable"), UNKNOWN("server_unknown");
    companion object {
        fun classify(code:String)=when(code) {
            "timeout"->TIMEOUT; "quota"->QUOTA; "voice"->VOICE; "safety"->SAFETY
            "auth"->AUTH; "unavailable"->UNAVAILABLE; else->UNKNOWN
        }
    }
}

internal object SessionTermination {
    fun accepts(reason:String,active:Boolean,permitted:Boolean,blocked:Boolean,currentScope:Boolean)=
        active && permitted && !blocked && currentScope && reason in setOf("conversation_ended","session_expired")
}
