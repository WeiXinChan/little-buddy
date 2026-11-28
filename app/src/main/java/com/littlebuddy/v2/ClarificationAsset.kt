package com.littlebuddy.v2

import android.content.res.AssetManager
import java.security.MessageDigest

/** Fixed system prompt only. Never accepts a path, text, credential or network source. */
internal object ClarificationAsset {
    fun load(assets:AssetManager):ShortArray {
        val expected=assets.open("v2-local-clarify.sha256").bufferedReader().use{it.readText().trim()}
        require(expected.matches(Regex("[0-9a-f]{64}")))
        val bytes=assets.open("v2-local-clarify.pcm").use{input->
            val value=input.readBytesLimited(288000)
            require(value.size in 480..288000 && value.size%2==0)
            value
        }
        try {
            val digest=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02x".format(it)}
            check(digest==expected)
            return ShortArray(bytes.size/2){i->((bytes[2*i].toInt() and 255) or (bytes[2*i+1].toInt() shl 8)).toShort()}
        } finally {bytes.fill(0)}
    }
    private fun java.io.InputStream.readBytesLimited(max:Int):ByteArray {
        val bytes=ByteArray(max+1)
        try {
            var count=0
            while(count<bytes.size){val n=read(bytes,count,bytes.size-count);if(n<0)break;check(n>0);count+=n}
            require(count<=max)
            return bytes.copyOf(count)
        } finally {bytes.fill(0)}
    }
}
