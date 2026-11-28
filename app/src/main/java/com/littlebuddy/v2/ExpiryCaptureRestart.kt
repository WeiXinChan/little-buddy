package com.littlebuddy.v2

/** One fresh recorder retry, only on the new idle transport created by accepted normal TTL.
 * Never authorizes PCM admission, network retry, or a different failure/capture/lifecycle. */
internal class ExpiryCaptureRestart {
    private var transport:Long?=null
    private var capture:Long?=null
    private var used=false
    @Synchronized fun arm(afterReleaseTransport:Long) {transport=afterReleaseTransport;capture=null;used=false}
    @Synchronized fun started(currentTransport:Long,currentCapture:Long) {
        if(transport==currentTransport && capture==null)capture=currentCapture
    }
    @Synchronized fun consume(currentTransport:Long,currentCapture:Long,reason:CaptureClockReason?,
        permitted:Boolean,idle:Boolean,released:Boolean):Boolean {
        if(transport!=currentTransport || capture!=currentCapture || used || !permitted || !idle || !released ||
            reason!=CaptureClockReason.STARTUP_NATIVE_CONTINUITY_EXHAUSTED)return false
        used=true;return true
    }
    @Synchronized fun cancel(){transport=null;capture=null;used=false}
}
