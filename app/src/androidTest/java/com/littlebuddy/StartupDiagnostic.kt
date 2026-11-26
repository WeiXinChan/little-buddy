package com.littlebuddy

internal enum class StartupMode { TIMESTAMP_ONLY, READ_THEN_TIMESTAMP }
internal data class StartupApiSample(val code:Int,val frames:Long=-1,val nanoTime:Long=-1)
internal interface StartupPort {
    fun nowMs():Long
    fun allowed():Boolean
    fun read(samples:ShortArray,count:Int):Int
    fun timestamp():StartupApiSample
    fun pause(ms:Long)
}
internal class StartupDiagnosticStopped(val code:String):IllegalStateException(code)
internal class StartupObservation(val mode:StartupMode) {
    var elapsedMs=0L;var apiCalls=0;var readCalls=0;var readSamples=0L;var lastReadCode=Int.MIN_VALUE
    val codes=sortedMapOf<Int,Int>()
    var firstSuccessMs=-1L;var firstSuccessFrames=-1L;var firstSuccessNs=-1L
    var firstWindowSuccessMs=-1L;var firstWindowWellFormedMs=-1L;var lateApiCalls=0;var lateSuccesses=0;var lateWellFormed=0
    var firstWellFormedMs=-1L;var invalidPairs=0;var positionRegressions=0;var timeRegressions=0
    var lastFrames=-1L;var lastNs=-1L;var maxApiMs=0L;var maxAgeNs=Long.MIN_VALUE
    var terminal="NOT_STARTED"
}
/** TEST ONLY: unanchored data is discarded, never retained or passed to the production ledger.
 * Fixed limits cannot be enlarged by instrumentation arguments. No read/PCM consumer exists. */
internal object StartupDiagnostic {
    const val WINDOW_MS=1000L
    const val INTERVAL_MS=10L
    const val MAX_STEPS=128
    const val MAX_SAMPLES=19200L // one second plus the original 3200-sample buffer
    const val FRAME_SAMPLES=320
    fun run(port:StartupPort,result:StartupObservation) {
        val frame=ShortArray(FRAME_SAMPLES)
        val began=port.nowMs()
        fun checkpoint(){if(!port.allowed())throw StartupDiagnosticStopped("DIAG_CANCELLED")
            if(port.nowMs()<began)throw StartupDiagnosticStopped("DIAG_CLOCK_REGRESSED")}
        fun exhausted():Boolean {
                checkpoint();result.elapsedMs=port.nowMs()-began
                result.terminal=when {
                    result.elapsedMs>=WINDOW_MS->"WINDOW_LIMIT"
                    result.apiCalls>=MAX_STEPS->"STEP_LIMIT"
                    result.readSamples>=MAX_SAMPLES->"SAMPLE_LIMIT"
                    else->"RUNNING"
                }
                return result.terminal!="RUNNING"
        }
        try {
            while(true){
                if(exhausted())break
                if(result.mode==StartupMode.READ_THEN_TIMESTAMP){
                    val request=minOf(FRAME_SAMPLES.toLong(),MAX_SAMPLES-result.readSamples).toInt()
                    try {
                        result.readCalls++;val count=port.read(frame,request);result.lastReadCode=count
                        if(count !in 0..request)throw StartupDiagnosticStopped("DIAG_NATIVE_READ_ERROR")
                        result.readSamples+=count
                    }finally{frame.fill(0)}
                }
                if(exhausted())break // A read may have consumed the entire budget. Never start another API.
                val before=port.nowMs();result.apiCalls++
                val stamp=port.timestamp();val after=port.nowMs();checkpoint()
                result.maxApiMs=maxOf(result.maxApiMs,after-before)
                val inWindow=after-began<WINDOW_MS
                if(!inWindow)result.lateApiCalls++
                result.codes[stamp.code]=(result.codes[stamp.code] ?: 0)+1
                if(stamp.code==0){
                    if(inWindow){if(result.firstWindowSuccessMs<0)result.firstWindowSuccessMs=after-began}else result.lateSuccesses++
                    if(result.firstSuccessMs<0){result.firstSuccessMs=after-began;result.firstSuccessFrames=stamp.frames;result.firstSuccessNs=stamp.nanoTime}
                    val valid=stamp.frames>=0 && stamp.nanoTime>=0 && stamp.nanoTime<=after*1_000_000+1_000_000
                    if(!valid)result.invalidPairs++ else {
                        if(result.firstWellFormedMs<0)result.firstWellFormedMs=after-began
                        if(inWindow){if(result.firstWindowWellFormedMs<0)result.firstWindowWellFormedMs=after-began}else result.lateWellFormed++
                    }
                    if(result.lastFrames>=0 && stamp.frames<result.lastFrames)result.positionRegressions++
                    if(result.lastNs>=0 && stamp.nanoTime<result.lastNs)result.timeRegressions++
                    result.lastFrames=stamp.frames;result.lastNs=stamp.nanoTime
                    result.maxAgeNs=maxOf(result.maxAgeNs,after*1_000_000-stamp.nanoTime)
                }
                result.elapsedMs=after-began
                val left=WINDOW_MS-result.elapsedMs
                if(left>0)port.pause(minOf(INTERVAL_MS,left))
            }
        }finally{frame.fill(0);result.elapsedMs=port.nowMs()-began}
    }
    fun interpretation(a:StartupObservation,b:StartupObservation):String=when {
        a.invalidPairs+b.invalidPairs+a.positionRegressions+b.positionRegressions+a.timeRegressions+b.timeRegressions>0->"API_PAIR_ANOMALY"
        a.firstWindowWellFormedMs>=0 && b.firstWindowWellFormedMs>=0->"BOTH_AVAILABLE_IN_WINDOW"
        a.firstWindowWellFormedMs<0 && b.firstWindowWellFormedMs>=0->"READ_PATH_OR_ORDER_WARMUP_ASSOCIATION"
        a.firstWindowWellFormedMs>=0->"SESSION_VARIABILITY"
        else->"UNAVAILABLE_IN_TWO_WINDOWS_NOT_PERMANENT_UNSUPPORTED"
    }
}
