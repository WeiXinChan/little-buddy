package com.littlebuddy

import java.io.InputStream
import java.security.MessageDigest

internal data class WakeAsset(val path:String,val bytes:Int,val sha256:String)
internal object FrozenWakeInputs {
    val fixtures=listOf(
        WakeAsset("wake/command-alone.pcm",122928,"6bd307fe4c8084992908b27bc6f458f64e7af59297bb2d2099685452a45ca5c2"),
        WakeAsset("wake/wake.pcm",112600,"9e0dc7461fb79ea34a0bb50932132b590cc51dcc183519d3bcf03dc545f16c3b"),
        WakeAsset("wake/gap-120.pcm",159368,"419547b87e86ca7ec593c0ef6f594cf293a51aef0e0787ae6f2dab4ec2650dda"))
    val models=listOf(
        WakeAsset("wake/encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx",4599656,"408bbd740838c42d5bf6d1c5b80b3c88b616c7860b92d980328b5b068c76ae48"),
        WakeAsset("wake/decoder-epoch-13-avg-2-chunk-16-left-64.onnx",759829,"63a22dd60f40fff082ac3e09afa507f6787da36df76ded2fbe145fa233e22c21"),
        WakeAsset("wake/joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx",86629,"190d4067b4cc20b72a42a1916e69d92052000fb7051a427ebb1bc72a69207dc1"),
        WakeAsset("wake/tokens.txt",1928,"2d3f32311f9b692b964da3c90e830258d3e78e013cb0c992dbfb15cd5a1a71b0"),
        WakeAsset("wake/keywords.txt",34,"d6ca8e845963fa305acd3599e2eac5de3c9c734faad914413f583c19a55d1d98"))
}
internal class WakeProbeViolation(val code:String):IllegalStateException(code)
internal class WakeProbeDependency(val code:String):org.junit.AssumptionViolatedException(code)
internal fun wakeRequire(valid:Boolean,code:String){if(!valid)throw WakeProbeViolation(code)}
internal fun classifyWakeFailure(error:Throwable,lost:()->Boolean):Throwable=when {
    error is WakeProbeViolation || error is WakeProbeDependency->error
    lost()->WakeProbeDependency("DEPENDENCY_WAKE_FOREGROUND_LOST")
    error is SecurityException->WakeProbeDependency("DEPENDENCY_WAKE_OS_POLICY")
    else->error
}
internal class WakeProbeBudget(private val wall:()->Long,private val cpu:()->Long) {
    companion object {const val WALL_MS=60_000L;const val CPU_MS=45_000L;const val SAMPLE_CAP=229_448L}
    private val wallStart=wall();private val cpuStart=cpu()
    private var lastWall=wallStart;private var lastCpu=cpuStart
    var wallMs=0L;private set
    var cpuMs=0L;private set
    fun check(samples:Long){
        val w=wall();val c=cpu()
        wakeRequire(w>=lastWall && c>=lastCpu,"WAKE_CLOCK_REGRESSED");lastWall=w;lastCpu=c
        wallMs=w-wallStart;cpuMs=c-cpuStart
        wakeRequire(wallMs<WALL_MS,"WAKE_WALL_BUDGET")
        wakeRequire(cpuMs<CPU_MS,"WAKE_CPU_BUDGET")
        wakeRequire(samples in 0..SAMPLE_CAP,"WAKE_SAMPLE_BUDGET")
    }
}
internal interface WakeProbeEngine:AutoCloseable {fun accept(samples:ShortArray,count:Int):Long?}
internal data class WakeCaseResult(val id:String,val fixtureSamples:Int,val fed:Int,val hits:Int,val tail:Long?,val wallMs:Long)

/** Shared bounded orchestration; only the instrumentation factory binds real SherpaWake/target assets. */
internal class WakeFixtureKernel(
    val budget:WakeProbeBudget,private val allowed:()->Boolean,
    private val targetAsset:(String)->InputStream,private val fixtureAsset:(String)->InputStream,
    private val engine:(()->Boolean)->WakeProbeEngine
) {
    private val hashScratch=ByteArray(8192);private val bytes=ByteArray(640);private val samples=ShortArray(320)
    @Volatile var attempted=0;private set
    @Volatile var constructed=0;private set
    @Volatile var closed=0;private set
    @Volatile var totalFed=0L;private set
    @Volatile var hashesVerified=false;private set
    @Volatile var cleanupClass="";private set
    @Volatile var phase="hashes";private set
    var currentCase="";private set
    var currentOffered=0;private set
    var currentHits=0;private set
    var currentTail:Long?=null;private set
    val results=mutableListOf<WakeCaseResult>() // Read by caller only after worker joined.
    fun clear(){hashScratch.fill(0);bytes.fill(0);samples.fill(0)}
    internal fun scratchIsClear()=hashScratch.all{it==0.toByte()} && bytes.all{it==0.toByte()} && samples.all{it==0.toShort()}
    fun checkpoint(){budget.check(totalFed);if(!allowed())throw WakeProbeDependency("DEPENDENCY_WAKE_FOREGROUND_LOST")}
    private fun hash(asset:WakeAsset,open:(String)->InputStream){
        val digest=MessageDigest.getInstance("SHA-256");var count=0
        try {open(asset.path).use { input->while(true){
            checkpoint();val n=input.read(hashScratch);checkpoint()
            if(n<0)break
            wakeRequire(n>0 && n<=hashScratch.size,"WAKE_ASSET_READ_PROGRESS")
            count+=n;wakeRequire(count<=asset.bytes,"WAKE_ASSET_SIZE")
            digest.update(hashScratch,0,n);hashScratch.fill(0)
        }}
        wakeRequire(count==asset.bytes,"WAKE_ASSET_SIZE")
        wakeRequire(digest.digest().joinToString(""){"%02x".format(it.toInt() and 255)}==asset.sha256,"WAKE_ASSET_HASH")
        }finally{hashScratch.fill(0)}
    }
    fun run(){
        try {
            FrozenWakeInputs.models.forEach{hash(it,targetAsset)}
            FrozenWakeInputs.fixtures.forEach{hash(it,fixtureAsset)};hashesVerified=true
            runCase("silence",null,32000,false)
            for((index,asset) in FrozenWakeInputs.fixtures.withIndex())runCase(
                listOf("command_alone","wake","gap_120")[index],asset,asset.bytes/2,index!=0)
            checkpoint();wakeRequire(results.size==4 && attempted==4 && constructed==4 && closed==4,"WAKE_MODEL_COMPLETION")
        }finally{clear();budget.check(totalFed)} // Final witness also runs on cancellation/close exceptions.
    }
    private fun runCase(id:String,asset:WakeAsset?,limit:Int,expectHit:Boolean){
        currentCase=id;currentOffered=0;currentHits=0;currentTail=null
        checkpoint();phase="model_create";attempted++
        // A constructor exception may have allocated native state: do NOT claim it released.
        val model=engine{checkpoint();true};constructed++
        var fed=0;var hit:Long?=null;val began=budget.wallMs
        try {
            checkpoint();phase="fixture_accept"
            val input=asset?.let{fixtureAsset(it.path)}
            try {while(fed<limit){
                checkpoint();val size=minOf(320,limit-fed)
                try {
                    if(input!=null){
                        var have=0
                        while(have<size*2){checkpoint();val n=input.read(bytes,have,size*2-have);checkpoint()
                            wakeRequire(n>0,"WAKE_FIXTURE_TRUNCATED");have+=n}
                        for(i in 0 until size)samples[i]=((bytes[2*i].toInt() and 255) or (bytes[2*i+1].toInt() shl 8)).toShort()
                    }
                    checkpoint();totalFed+=size;budget.check(totalFed)
                    currentOffered=fed+size
                    hit=model.accept(samples,size);fed+=size
                    currentTail=hit;currentHits=if(hit==null)0 else 1
                    // Witness returned native evidence before later revocation may stop continuation.
                    if(hit!=null){wakeRequire(expectHit,"WAKE_UNEXPECTED_HIT")
                        wakeRequire(hit>0 && hit<=fed,"WAKE_TAIL_OUTSIDE_INPUT")}
                    checkpoint() // Valid hit + cancellation is dependency, never successful completion.
                    if(hit!=null)break
                }finally{bytes.fill(0);samples.fill(0)}
            }}finally{input?.close()}
            wakeRequire((hit!=null)==expectHit,"WAKE_EXPECTED_HIT_MISSING")
            results.add(WakeCaseResult(id,limit,fed,if(hit==null)0 else 1,hit,budget.wallMs-began))
        }finally{
            clear();phase="model_close"
            try {model.close();closed++}catch(error:Throwable){cleanupClass=probeFailureClass(error);throw error}
            // No budget/foreground guard can skip close; a late close is checked afterwards.
        }
        checkpoint()
    }
}
internal object WakeProbeSelection {
    const val METHOD="com.littlebuddy.NativeWakeModelTest#packagedProductionModelOnFrozenFixtures"
    private val keys=setOf("class","nativeWakeModelProbe","businessIdlePreflight","knownWakeFixtures","disableAnalytics")
    fun permitsKeys(value:Set<String>)=value.all{it in keys}
    fun permits(method:String?,probe:String?,idle:String?,fixtures:String?)=
        method==METHOD && probe=="true" && idle=="true" && fixtures=="true"
}
