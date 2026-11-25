package com.littlebuddy

/** Shared by the actual stop thread and host regressions. Never retain/serialize native messages. */
internal fun probeFailureClass(error:Throwable)=error.javaClass.simpleName.ifBlank { "Throwable" }

internal fun guardedProbeStop(action:()->Unit,onFailure:(String)->Unit) {
    try {action()}catch(error:Throwable){onFailure(probeFailureClass(error))}
}
internal data class ProbeReleaseProof(val required:Boolean,val nativeStopped:Boolean,val nativeReleased:Boolean,
    val workerJoined:Boolean,val stopJoined:Boolean,val ownedLeaseComplete:Boolean) {
    val confirmed get()=!required || (nativeStopped && nativeReleased && workerJoined && stopJoined && ownedLeaseComplete)
}
internal data class ProbeDecision(val outcome:String,val reason:String,val dependencyReason:String,
    val exceptionClass:String,val junitFailure:Boolean) {
    fun enforce() {
        if(junitFailure)throw AssertionError("native timestamp probe: $reason; exception=$exceptionClass")
        if(outcome=="NOT_RUN_DEPENDENCY")throw org.junit.AssumptionViolatedException(dependencyReason)
        check(outcome=="PASS")
    }
    fun json():String {
        fun quote(value:String)=buildString {
            append('"');value.forEach {c->when(c){'"'->append("\\\"");'\\'->append("\\\\");else->
                if(c<' ')append("\\u"+c.code.toString(16).padStart(4,'0')) else append(c)}};append('"')
        }
        return "{\"outcome\":"+quote(outcome)+",\"reason\":"+quote(reason)+
            ",\"dependency_reason\":"+quote(dependencyReason)+",\"exception_class\":"+quote(exceptionClass)+
            ",\"junit_failure\":"+junitFailure+"}"
    }
}
/** Resource failures dominate dependency for BOTH result metadata and the actual JUnit verdict. */
internal fun decideProbeResult(dependency:String,originalReason:String,originalClass:String,
    cleanupClass:String,stopClass:String,proof:ProbeReleaseProof):ProbeDecision = when {
    cleanupClass.isNotEmpty()->ProbeDecision("FAIL","NATIVE_CLEANUP_EXCEPTION",dependency,cleanupClass,true)
    stopClass.isNotEmpty()->ProbeDecision("FAIL","NATIVE_STOP_REQUEST_FAILED",dependency,stopClass,true)
    !proof.confirmed->ProbeDecision("FAIL","NATIVE_CLEANUP_UNCONFIRMED",dependency,originalClass,true)
    dependency.isNotEmpty()->ProbeDecision("NOT_RUN_DEPENDENCY",dependency,dependency,originalClass,false)
    originalReason.isNotEmpty()->ProbeDecision("FAIL",originalReason,"",originalClass,true)
    else->ProbeDecision("PASS","","","",false)
}
