package com.littlebuddy.v2

import android.content.res.AssetManager
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Actual V2 Kotlin adapter + source-patched JNI + real packaged ONNX, fixed synthetic stdin. */
fun main(args:Array<String>) {
    val raw=System.`in`.readNBytes(320001);check(raw.size in 2..320000 && raw.size%2==0)
    val pcm=ShortArray(raw.size/2);ByteBuffer.wrap(raw).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(pcm);raw.fill(0)
    val started=System.nanoTime()
    try {
        val assets=AssetManager(File(args[0]));val directory=File(args[1]);check(directory.mkdirs() || directory.isDirectory)
        val cancelled=AbsoluteWake(assets,directory){false}
        try {cancelled.initialize();check(cancelled.accept(ShortArray(320),320)==null)}finally{cancelled.close();cancelled.close()}
        var copyAllowed=true
        val cancelDir=File(directory,"cancel-copy");check(cancelDir.mkdirs())
        val cancelAssets=AssetManager(File(args[0])){copyAllowed=false}
        val copying=AbsoluteWake(cancelAssets,cancelDir){copyAllowed}
        try {check(runCatching{copying.initialize()}.isFailure)}finally{copying.close()}
        check(cancelDir.walkTopDown().none{it.isFile}) {"cancelled model copy left material"}
        println("MODEL_INIT cancelled_before_native=1 cancelled_copy_cleanup=1")
        for(prefix in listOf(0,30,90)) {
            var allowed=true
            val model=AbsoluteWake(assets,directory){allowed};val frame=ShortArray(320)
            var fed=0L;var tail:Long?=null
            try {
                model.initialize()
                while(fed<prefix*16000L) {
                    check(System.nanoTime()-started<120_000_000_000L)
                    check(model.accept(frame,320)==null){"unexpected silence hit"};fed+=320
                }
                var cursor=0
                while(tail==null && cursor<pcm.size+32000) {
                    frame.fill(0)
                    for(i in frame.indices)if(cursor+i<pcm.size)frame[i]=pcm[cursor+i]
                    try {tail=model.accept(frame,320)} finally {frame.fill(0)}
                    fed+=320;cursor+=320
                }
                val real=checkNotNull(tail){"fixed native cue did not hit"}
                println("NATIVE_OBSERVED prefix_s=$prefix fed=$fed native_tail=$real")
                check(real>prefix*16000L && real<=fed && fed-real<16000) {"native coordinate outside submitted cue window"}
                // Feed-derived monotonic test clock only; no synthetic coordinate correction.
                var now=100000+fed/16+3500
                var solos=0
                val gate=InputGate(Waits(),{now},{},{},{},{solos++},{},{})
                val observedAt=100000+real/16
                gate.wake(observedAt);gate.tick(false)
                check(solos==1 && gate.responseDeadline==observedAt+15000)
                allowed=false;check(model.accept(frame,320)==null)
                println("NATIVE_ORIGIN prefix_s=$prefix fed=$fed native_tail=$real lag_samples=${fed-real} boot_relative_ms=${real/16} response_deadline_delta=${gate.responseDeadline-now} solo=$solos")
            } finally {frame.fill(0);model.close();model.close()}
        }
        val stored=File(directory,"v2-kws-1.12.27-model1/tokens.txt")
        val before=stored.readBytes();stored.writeBytes(ByteArray(before.size))
        val corrupt=AbsoluteWake(assets,directory){true}
        try {check(runCatching{corrupt.initialize()}.isFailure);check(stored.readBytes().all{it==0.toByte()})}finally{corrupt.close();stored.writeBytes(before);before.fill(0)}
        println("MODEL_INIT corrupt_cache_rejected=1 existing_cache_not_reset=1")
    } finally {pcm.fill(0)}
    println("NATIVE_ORIGIN completed=3 models_release_returned=true no_recorder=true no_provider=true")
}
