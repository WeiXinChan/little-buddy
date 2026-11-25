package com.littlebuddy.v2

import java.nio.ByteBuffer
import java.security.MessageDigest
import java.util.zip.CRC32
import java.util.zip.Inflater

/** One sequential bounded buffer, no URLs/files. Failure destroys the slot before returning. */
internal class PngAssembly(private val now: ()->Long) {
    data class Completed(val ready: ImageReady, val ticket: Long, val bytes: ByteArray)
    private var ready: ImageReady?=null
    private var buffer: ByteArray?=null
    private var ticket=0L
    private var offset=0;private var index=0;private var chunks=0
    private var deadline=0L
    @Synchronized fun clear() { buffer?.fill(0);buffer=null;ready=null;offset=0;index=0 }
    @Synchronized fun begin(value: ImageReady, ticket: Long, bytes: Int, chunks: Int, chunkBytes: Int, retainMs: Long) {
        clear()
        require(bytes in 1..2_097_152 && chunks in 1..256 && chunkBytes==8192 && chunks==(bytes+8191)/8192)
        require(value.source=="dynamic" && value.asset.width in 512..2048 && value.asset.height in 512..2048 && retainMs in 1..15000)
        this.ready=value;this.ticket=ticket;this.buffer=ByteArray(bytes);this.chunks=chunks
        deadline=now()+minOf(2000,retainMs)
    }
    @Synchronized fun chunk(value: ImageReady, index: Int, offset: Int, data: ByteArray) {
        try {
            val b=checkNotNull(buffer)
            require(value==ready && now()<deadline && index==this.index && offset==this.offset)
            require(data.size==minOf(8192,b.size-offset) && data.isNotEmpty() && index<chunks)
            data.copyInto(b,offset);this.offset+=data.size;this.index++
        } catch(f: Exception) { clear();throw f } finally { data.fill(0) }
    }
    @Synchronized fun expired() = buffer!=null && now()>=deadline
    @Synchronized fun finish(value: ImageReady): Completed {
        try {
            val b=checkNotNull(buffer)
            require(value==ready && now()<deadline && offset==b.size && index==chunks)
            buffer=null;ready=null;return Completed(value,ticket,b)
        } catch(f: Exception) { clear();throw f }
    }
    companion object {
        /** Provider publishes canonical IHDR/IDAT/IEND only; rejects animation, metadata and zip bombs. */
        fun validate(data: ByteArray, width: Int, height: Int) {
            require(data.size in 57..2_097_152 && width in 512..2048 && height in 512..2048)
            require(data.copyOfRange(0,8).contentEquals(byteArrayOf(-119,80,78,71,13,10,26,10)))
            val b=ByteBuffer.wrap(data);b.position(8)
            var compressed: ByteArray?=null;var color=0
            for(kind in listOf("IHDR","IDAT","IEND")) {
                require(b.remaining()>=12);val n=b.int;require(n>=0 && n<=b.remaining()-8)
                val name=ByteArray(4).also{b.get(it)};require(String(name,Charsets.US_ASCII)==kind)
                val part=ByteArray(n).also{b.get(it)};val crc=b.int.toLong() and 0xffffffffL
                require(CRC32().apply{update(name);update(part)}.value==crc)
                when(kind) {
                    "IHDR"->{ require(n==13);val h=ByteBuffer.wrap(part)
                        require(h.int==width && h.int==height && h.get().toInt()==8)
                        color=h.get().toInt();require(color==2 || color==6)
                        require(h.get().toInt()==0 && h.get().toInt()==0 && h.get().toInt()==0) }
                    "IDAT"->{require(n>0);compressed=part}
                    else->require(n==0 && !b.hasRemaining())
                }
            }
            val inflater=Inflater();val stride=width*(if(color==2)3 else 4)+1;val expected=stride*height
            val row=ByteArray(stride);var total=0
            try {
                inflater.setInput(checkNotNull(compressed))
                while(!inflater.finished()) {
                    val count=inflater.inflate(row);if(count==0) { require(inflater.finished());break };require(total+count<=expected)
                    for(i in 0 until count)if((total+i)%stride==0)require(row[i].toInt() in 0..4)
                    total+=count
                }
                require(total==expected && inflater.remaining==0)
            } finally { inflater.end();row.fill(0);compressed?.fill(0) }
        }
    }
}
