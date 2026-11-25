package com.littlebuddy.v2

import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.util.zip.CRC32
import java.util.zip.Deflater
import java.security.MessageDigest

class MediaControlsTest {
    private val scope=ImageScope("a".repeat(32),1,0,2)
    private val token="b".repeat(32)
    private fun png(): ByteArray {
        val raw=ByteArray((512*4+1)*512);val d=Deflater();d.setInput(raw);d.finish()
        val out=ByteArrayOutputStream();val tmp=ByteArray(8192)
        while(!d.finished())out.write(tmp,0,d.deflate(tmp));d.end()
        fun chunk(kind:String,data:ByteArray):ByteArray {
            val o=ByteArrayOutputStream();DataOutputStream(o).use { w->w.writeInt(data.size);w.writeBytes(kind);w.write(data)
                w.writeInt(CRC32().apply{update(kind.toByteArray());update(data)}.value.toInt()) };return o.toByteArray()
        }
        val h=ByteArrayOutputStream();DataOutputStream(h).use{it.writeInt(512);it.writeInt(512);it.write(byteArrayOf(8,6,0,0,0))}
        return byteArrayOf(-119,80,78,71,13,10,26,10)+chunk("IHDR",h.toByteArray())+chunk("IDAT",out.toByteArray())+chunk("IEND",byteArrayOf())
    }
    private fun ready(bytes:ByteArray=png())=ImageReady(scope,3,token,ImageAsset("dragon",MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02x".format(it)},512,512),"c".repeat(32),"dynamic")
    private fun rejected(block:()->Unit) { try {block();fail("unsafe acceptance")}catch(_:IllegalArgumentException){}catch(_:IllegalStateException){} }
    @Test fun volumeIsBoundedTemporaryAndScopeSingleUse() {
        val v=ChildVolume(45);val s=ManagementScope(scope.session,1,0,2);v.bind(s)
        assertEquals(35,v.accept(s,token,"down"));assertNull(v.accept(s,token,"up"));assertEquals(35,v.value)
        v.bind(s.copy(revision=3));assertNull(v.accept(s,token,"up"));assertEquals(45,v.accept(s.copy(revision=3),token,"up"))
        v.tighten(20);assertEquals(20,v.value);v.clear();assertNull(v.accept(s.copy(revision=3),token,"up"))
    }
    @Test fun volumeUpdateDoesNotPlayOrResumePausedTrack() {
        class Track:TrackPort {var plays=0;var value=0;override val head=0L
            override fun setVolume(percent:Int):Boolean { value=percent;return true };override fun write(pcm:ShortArray,offset:Int)=0
            override fun play(){plays++};override fun pause(){};override fun mute(){};override fun flush(){};override fun stop(){};override fun release(){} }
        val t=Track();val p=Playback({t},{0L},{})
        p.bind(Binding(0,"p",1));p.suspendOutput();p.setVolume(20)
        assertEquals(20,t.value);assertEquals(0,t.plays);assertTrue(p.suspended);p.stop();p.setVolume(10);assertEquals(20,t.value)
    }
    @Test fun boundedAssemblyProducesRealPngAndChecksDimensionsCrcAndInflate() {
        val b=png();val r=ready(b);val a=PngAssembly{0L};a.begin(r,7,b.size,1,8192,15000);a.chunk(r,0,0,b.copyOf())
        val result=a.finish(r);assertEquals(7L,result.ticket);assertArrayEquals(b,result.bytes);PngAssembly.validate(result.bytes,512,512)
        rejected{PngAssembly.validate(b,1024,512)};val bad=b.copyOf();bad[40]=(bad[40].toInt() xor 1).toByte();rejected{PngAssembly.validate(bad,512,512)}
    }
    @Test fun sequenceOffsetMetadataAndTimeoutDestroyAssembly() {
        val b=png();val r=ready(b)
        for(mode in 0..3) {var now=0L;val a=PngAssembly{now};a.begin(r,1,b.size,1,8192,15000)
            when(mode) {0->rejected{a.chunk(r,1,0,b.copyOf())};1->rejected{a.chunk(r,0,1,b.copyOf())}
                2->rejected{a.chunk(r.copy(scope=scope.copy(revision=3)),0,0,b.copyOf())}
                else->{now=2000;assertTrue(a.expired());rejected{a.chunk(r,0,0,b.copyOf())}} }
            rejected{a.finish(r)}
        }
    }
    @Test fun rejectsOversizeAndDuplicateChunkAndClear() {
        val b=png();val r=ready();val a=PngAssembly{0L}
        rejected{a.begin(r,1,2_097_153,257,8192,15000)};rejected{a.begin(r,1,b.size,1,9000,15000)}
        a.begin(r,1,b.size,1,8192,15000);a.chunk(r,0,0,b.copyOf());rejected{a.chunk(r,0,0,b.copyOf())};rejected{a.finish(r)}
        a.begin(r,1,b.size,1,8192,15000);a.clear();rejected{a.finish(r)}
    }
    @Test fun sixSecondHideAndFinalMaterialDeadlineCannotBeExtended() {
        var now=0L;var released=0;val r=ready();val g=ImageGate<String>({now},{released++}){}
        fun visible():String? {var s:String?=null;g.render{s=it};return s}
        g.bind(scope);g.loaded(g.prepare(r)!!,"pixels");g.acknowledged("p",1,"s",10)
        assertTrue(g.display(ImageReveal(r,"p",1,"s",10),"display",6000,15000));assertEquals("pixels",visible())
        now=6000;g.tick();assertNull(visible())
        val r2=r.copy(token="d".repeat(32));assertTrue(g.display(ImageReveal(r2,"p",1,"s",10),"reshow",6000,15000))
        now=11000;val r3=r.copy(token="e".repeat(32));assertTrue(g.display(ImageReveal(r3,"p",1,"s",10),"extend",12000,15000))
        now=15000;g.tick();assertNull(visible());assertEquals(1,released);assertNull(g.prepare(r.copy(token="f".repeat(32))))
    }
    @Test fun storyTwelveSecondsAndExactAckBeforeAnyPublication() {
        var now=0L;val r=ready();val g=ImageGate<String>({now}){};g.bind(scope);g.loaded(g.prepare(r)!!,"pixels")
        val d=ImageReveal(r,"p",1,"s",10);assertFalse(g.display(d,"display",12000,15000));g.acknowledged("p",1,"s",9)
        assertFalse(g.display(d,"display",12000,15000));g.acknowledged("p",1,"s",10);assertTrue(g.display(d,"display",12000,15000))
        now=11999;var value:String?=null;g.render{value=it};assertEquals("pixels",value);now++;g.render{value=it};assertNull(value)
    }
    @Test fun reshowAcrossInputNeedsNewScopeAndAckAndKeepsDeadline() {
        var now=0L;val r=ready();val g=ImageGate<String>({now}){};g.bind(scope);g.loaded(g.prepare(r)!!,"pixels")
        g.acknowledged("p",1,"s",10);assertTrue(g.reveal(ImageReveal(r,"p",1,"s",10)))
        now=5000;g.inputChanged();val next=scope.copy(revision=3);g.bind(next)
        val n=r.copy(scope=next,token="d".repeat(32));val proof=ImageReveal(n,"p2",2,"s2",20)
        assertFalse(g.display(proof,"reshow",6000,15000));g.acknowledged("p2",2,"s2",20);assertTrue(g.display(proof,"reshow",6000,15000))
        now=15000;g.tick();var visible:String?="bad";g.render{visible=it};assertNull(visible)
    }
    @Test fun lateDecodedValuesDisposedAfterHomeAndReplacement() {
        var disposed=0;val r=ready();val g=ImageGate<String>({0L},{disposed++}){};g.bind(scope);val ticket=g.prepare(r)!!
        g.clear();g.loaded(ticket,"late");assertEquals(1,disposed);g.bind(scope);g.loaded(g.prepare(r)!!,"new");g.clear();assertEquals(2,disposed)
    }    @Test fun outputRevokeDropsPixelsButRetransmissionCannotRefreshMaterialDeadline() {
        var now=0L;var disposed=0;val r=ready();val g=ImageGate<String>({now},{disposed++}){}
        g.bind(scope);g.loaded(g.prepare(r)!!,"pixels");g.acknowledged("p",1,"s",10);assertTrue(g.reveal(ImageReveal(r,"p",1,"s",10)))
        now=5000;g.outputRevoked();assertEquals(1,disposed)
        val next=scope.copy(revision=3);g.bind(next);val n=r.copy(scope=next,topic=4,token="d".repeat(32))
        g.loaded(g.prepare(n,15000)!!,"retransmitted");g.acknowledged("p2",2,"s2",20)
        assertTrue(g.display(ImageReveal(n,"p2",2,"s2",20),"extend",12000,15000))
        now=15000;g.tick();var visible:String?="bad";g.render{visible=it};assertNull(visible);assertEquals(2,disposed)
    }

}
