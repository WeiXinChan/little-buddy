package com.littlebuddy

/** Test-only fixed observation window. No duration or sample budget comes from host arguments. */
internal class ProbeWindowEnded:RuntimeException()
internal class NativeProbeWindow(private val now:()->Long) {
    companion object { const val DURATION_MS=60_000L; const val SAMPLE_CAP=968_000L }
    private val start=now()
    private var last=start
    var ended=false;private set
    fun elapsedMs():Long {
        val value=now();check(value>=last){"probe observation clock regressed"};last=value
        return value-start
    }
    fun beforeApi(samples:Long) {
        check(samples in 0..SAMPLE_CAP){"probe observation sample cap"}
        if(elapsedMs()>=DURATION_MS){ended=true;throw ProbeWindowEnded()}
    }
    fun afterApi(samples:Long) {
        check(samples in 0..SAMPLE_CAP){"probe observation sample cap"}
        check(elapsedMs()<DURATION_MS){"probe observation API crossed deadline"}
    }
    fun requireComplete(samples:Long,positive:Long) {
        check(ended && elapsedMs()>=DURATION_MS && samples in 944_000..SAMPLE_CAP && positive>=2_900){"insufficient continuous reads"}
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
