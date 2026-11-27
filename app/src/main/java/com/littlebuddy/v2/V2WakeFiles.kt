package com.littlebuddy.v2

import android.content.res.AssetManager
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest

/** Only fixed public packaged models enter this app-private cache. Never PCM or credentials. */
internal object V2WakeFiles {
    private data class Pin(val name:String,val size:Long,val sha:String)
    private val pins=listOf(
        Pin("encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx",4599656,"408bbd740838c42d5bf6d1c5b80b3c88b616c7860b92d980328b5b068c76ae48"),
        Pin("decoder-epoch-13-avg-2-chunk-16-left-64.onnx",759829,"63a22dd60f40fff082ac3e09afa507f6787da36df76ded2fbe145fa233e22c21"),
        Pin("joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx",86629,"190d4067b4cc20b72a42a1916e69d92052000fb7051a427ebb1bc72a69207dc1"),
        Pin("tokens.txt",1928,"2d3f32311f9b692b964da3c90e830258d3e78e013cb0c992dbfb15cd5a1a71b0"),
        Pin("keywords.txt",34,"d6ca8e845963fa305acd3599e2eac5de3c9c734faad914413f583c19a55d1d98"))
    @Synchronized fun prepare(assets:AssetManager,parent:File,allowed:()->Boolean):Array<String> {
        check(allowed());check(!Files.isSymbolicLink(parent.toPath()))
        val dir=File(parent,"v2-kws-1.12.27-model1")
        check(!Files.isSymbolicLink(dir.toPath()) && (dir.isDirectory || dir.mkdirs()))
        return pins.map {pin->
            check(allowed());val file=File(dir,pin.name)
            check(!Files.isSymbolicLink(file.toPath()))
            if(!file.exists()) {
                val temp=File.createTempFile("model-",".part",dir)
                try {
                    val bytes=ByteArray(8192);var count=0L
                    try {
                        assets.open("wake/"+pin.name).use {input->temp.outputStream().use {output->
                            while(true) {
                                check(allowed());val n=input.read(bytes);if(n<0)break
                                count+=n;check(count<=pin.size);output.write(bytes,0,n)
                            }
                            output.fd.sync()
                        }}
                    } finally {bytes.fill(0)}
                    check(count==pin.size);verify(temp,pin,allowed)
                    check(allowed());Files.move(temp.toPath(),file.toPath(),StandardCopyOption.ATOMIC_MOVE)
                } finally {temp.delete()}
            }
            verify(file,pin,allowed);file.absolutePath
        }.toTypedArray()
    }
    private fun verify(file:File,pin:Pin,allowed:()->Boolean) {
        check(file.isFile && file.length()==pin.size)
        val hash=MessageDigest.getInstance("SHA-256");val bytes=ByteArray(8192)
        try {file.inputStream().use {input->while(true){check(allowed());val n=input.read(bytes);if(n<0)break;hash.update(bytes,0,n)}}}
        finally {bytes.fill(0)}
        check(hash.digest().joinToString(""){"%02x".format(it)}==pin.sha) {"packaged keyword model integrity"}
    }
}
