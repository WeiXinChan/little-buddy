package com.littlebuddy.v2

/** All fields must come from one held Capture under its native lock. */
internal data class CaptureReadSnapshot(val requested:Int,val actual:Int?,val nonce:String?,
    val session:Int?,val nativeSession:Int?,val frames:Long,val recording:Boolean) {
    val reading get()=session!=null && session==nativeSession && recording && frames>0
    fun readyFor(expectedNonce:String,source:CaptureInput)=reading && nonce==expectedNonce &&
        requested==source.value && actual==source.value
}
