package com.littlebuddy

/** Test-only fixed observation window. No duration or sample budget comes from host arguments. */
internal class ProbeWindowEnded:RuntimeException()
internal enum class ProbeInvariant(val safeReason:String) {
    CLOCK_REGRESSED("probe observation clock regressed"),
    SAMPLE_CAP("probe observation sample cap"),
    API_CROSSED_DEADLINE("probe observation API crossed deadline"),
    INCOMPLETE("insufficient continuous reads")
}
/** A witnessed invariant is a failure even if revocation arrives before catch/classification. */
internal class ProbeInvariantFailure(val invariant:ProbeInvariant):IllegalStateException(invariant.safeReason)
internal fun classifyNativeProbeFailure(error:Throwable,dependencyLost:()->Boolean,dependency:(String)->Throwable):Throwable=when {
    error is ProbeInvariantFailure->error
    dependencyLost()->dependency("DEPENDENCY_FOREGROUND_LOST")
    error is SecurityException->dependency("DEPENDENCY_NATIVE_PERMISSION_OR_POLICY")
    else->error
}
private fun requireProbeInvariant(valid:Boolean,invariant:ProbeInvariant) {
    if(!valid)throw ProbeInvariantFailure(invariant)
}
internal class NativeProbeWindow(private val now:()->Long) {
    companion object { const val DURATION_MS=60_000L; const val SAMPLE_CAP=968_000L }
    private val start=now()
    private var last=start
    var ended=false;private set
    fun elapsedMs():Long {
        val value=now();requireProbeInvariant(value>=last,ProbeInvariant.CLOCK_REGRESSED);last=value
        return value-start
    }
    fun beforeApi(samples:Long) {
        requireProbeInvariant(samples in 0..SAMPLE_CAP,ProbeInvariant.SAMPLE_CAP)
        if(elapsedMs()>=DURATION_MS){ended=true;throw ProbeWindowEnded()}
    }
    fun afterApi(samples:Long) {
        requireProbeInvariant(samples in 0..SAMPLE_CAP,ProbeInvariant.SAMPLE_CAP)
        requireProbeInvariant(elapsedMs()<DURATION_MS,ProbeInvariant.API_CROSSED_DEADLINE)
    }
    fun requireComplete(samples:Long,positive:Long) {
        requireProbeInvariant(ended && elapsedMs()>=DURATION_MS && samples in 944_000..SAMPLE_CAP && positive>=2_900,ProbeInvariant.INCOMPLETE)
    }
}
internal object NativeProbeSelection {
    const val SHORT="com.littlebuddy.NativeTimestampTest#nativeTimestampAndProductionLedger"
    const val LONG="com.littlebuddy.NativeTimestampTest#nativeTimestampAndProductionLedger60Seconds"
    const val STARTUP="com.littlebuddy.NativeTimestampStartupTest#compareTimestampStartup"
    const val CADENCE="com.littlebuddy.NativeTimestampCadenceTest#observeOneBoundedCadence"
    fun permits(method:String?,probe:String?,idle:String?,long:String?,startup:String?,cadence:String?)=
        probe=="true" && idle=="true" && when(method){
            SHORT->true
            LONG->long=="true"
            STARTUP->startup=="true"
            CADENCE->cadence=="true"
            else->false
        }
}
