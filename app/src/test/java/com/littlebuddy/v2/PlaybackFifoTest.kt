package com.littlebuddy.v2

import org.junit.Assert.*
import org.junit.Test

/** Synthetic PCM only; the native FIFO accepts short/zero writes and advances independently. */
class PlaybackFifoTest {
    private class Native:TrackPort {
        var position=0L
        var limit=Int.MAX_VALUE
        var released=false
        val submitted=mutableListOf<Short>()
        override val head get()=position
        override fun write(pcm:ShortArray,offset:Int):Int {
            val count=minOf(limit,pcm.size-offset)
            submitted.addAll(pcm.slice(offset until offset+count));return count
        }
        override fun play() {}
        override fun pause() {}
        override fun mute() {}
        override fun flush() {}
        override fun stop() {}
        override fun release() {released=true}
    }
    private val binding=Binding(1,"synthetic",1)
    private fun packet(start:Long,count:Int)=AudioPacket(binding,"s$start",start,start+count,
        ShortArray(count){(start+it+1).toInt().toShort()})
    @Test fun queuedPacketsWriteBeforeFirstHeadAndShortTailCompletesOnlyAtHead() {
        val native=Native();val acks=mutableListOf<PlaybackAck>()
        val player=Playback({native},{0L},acks::add)
        val packets=listOf(packet(0,2400),packet(2400,2400),packet(4800,17))
        player.bind(binding);packets.forEach {player.enqueue(it)}
        player.tick()
        assertEquals(4817,native.submitted.size)
        assertTrue(acks.none {it.completed})
        native.position=4800;player.tick()
        assertEquals(listOf("s0","s2400"),acks.filter {it.completed}.map {it.segment})
        assertTrue(packets[2].pcm.any {it!=0.toShort()})
        native.position=4816;player.tick();assertTrue(player.hasPending)
        native.position=4817;player.tick();assertFalse(player.hasPending)
        assertEquals(listOf(2400L,4800L,4817L),acks.filter {it.completed}.map {it.head})
        assertTrue(packets.all {p->p.pcm.all {it==0.toShort()}})
    }
    @Test fun zeroAndPartialWritesNeverDuplicateSkipOrAckUnplayedSamples() {
        val native=Native();val acks=mutableListOf<PlaybackAck>()
        val player=Playback({native},{0L},acks::add)
        val packets=listOf(packet(0,7),packet(7,3))
        player.bind(binding);packets.forEach {player.enqueue(it)}
        native.limit=0;repeat(3){player.tick()};assertEquals(0,native.submitted.size)
        native.limit=2;repeat(10){player.tick()}
        assertEquals((1..10).map {it.toShort()},native.submitted)
        assertTrue(acks.none {it.completed})
        player.stop();assertTrue(native.released)
        assertTrue(packets.all {p->p.pcm.all {it==0.toShort()}})
    }
    @Test fun suspendedQueueDoesNotPrewriteAndCancellationClearsAllSubmittedPcm() {
        val native=Native();val acks=mutableListOf<PlaybackAck>()
        val player=Playback({native},{0L},acks::add)
        val packets=listOf(packet(0,100),packet(100,23))
        player.bind(binding);packets.forEach {player.enqueue(it)}
        player.suspendOutput();player.tick();assertEquals(0,native.submitted.size)
        player.resumeConfirmedNoise();player.tick();assertEquals(123,native.submitted.size)
        native.position=50;player.tick()
        player.stop();native.position=123;player.tick()
        assertTrue(acks.none {it.completed})
        assertTrue(packets.all {p->p.pcm.all {it==0.toShort()}})
    }
    @Test fun ackCancellationCannotWriteOrConfirmNextPacket() {
        val native=Native();val acks=mutableListOf<PlaybackAck>()
        lateinit var player:Playback
        player=Playback({native},{0L}) {ack->acks+=ack;if(ack.completed)player.stop()}
        val packets=listOf(packet(0,100),packet(100,23))
        player.bind(binding);packets.forEach {player.enqueue(it)}
        player.tick();native.position=123;player.tick()
        assertEquals(1,acks.count {it.completed})
        assertNull(player.binding);assertTrue(native.released)
        assertTrue(packets.all {p->p.pcm.all {it==0.toShort()}})
    }
    private class FifoNative(private val capacity:Int):TrackPort {
        var position=0L
        var playing=false
        var released=false
        val submitted=mutableListOf<Short>()
        private val fifo=ArrayDeque<Short>()
        override val head get()=position
        override fun write(pcm:ShortArray,offset:Int):Int {
            val count=minOf(pcm.size-offset,capacity-fifo.size)
            for(i in offset until offset+count){fifo.addLast(pcm[i]);submitted+=pcm[i]}
            return count
        }
        fun consume():Int {
            if(!playing)return 0
            val n=minOf(24,fifo.size)
            repeat(n){fifo.removeFirst()};position+=n
            return n
        }
        override fun play(){playing=true}
        override fun pause(){playing=false}
        override fun mute(){}
        override fun flush(){fifo.clear()}
        override fun stop(){playing=false}
        override fun release(){released=true;fifo.clear()}
    }
    private data class WindowResult(val inStreamMissing:Long,val tailMissing:Long,val maxPending:Int)
    private fun twoPacketWindow(jitterMs:Long):WindowResult {
        val native=FifoNative(2400) // actual historical 100ms physical FIFO at 24kHz
        var time=0L;var pending=0;var maxPending=0;var sent=0;var next=0L
        var due=0L;var inStream=0L;var tail=0L
        val ackWire=ArrayDeque<Long>()
        val expected=mutableListOf<Short>()
        val complete=mutableListOf<String>()
        val player=Playback({native},{time}) {ack->
            if(ack.completed){complete+=ack.segment;ackWire.addLast(time+20L)}
        }
        player.bind(binding)
        // Same server admission rule as Voice.audio: at most two uncompleted ACKs.
        // Eight packets, each <=100ms; the final packet is deliberately short.
        for(ms in 0L..2200L) {
            time=ms
            while(ackWire.isNotEmpty() && ackWire.first()<=ms){ackWire.removeFirst();pending--}
            while(sent<8 && pending<2 && ms>=due) {
                val p=packet(next,if(sent==7)17 else 2400)
                expected.addAll(p.pcm.toList());next=p.end;player.enqueue(p)
                sent++;pending++;maxPending=maxOf(maxPending,pending)
                due=if(sent==3)ms+jitterMs else ms
            }
            if(ms%17L==0L)player.tick()
            val count=native.consume()
            if(native.position<16817L)inStream+=24-count else tail+=24-count
        }
        player.tick()
        assertEquals(8,sent);assertEquals(0,pending)
        assertEquals(8,complete.size);assertEquals(8,complete.toSet().size)
        assertEquals(expected,native.submitted)
        assertFalse(player.hasPending)
        player.stop();assertTrue(native.released)
        return WindowResult(inStream,tail,maxPending)
    }
    @Test fun realTwoPacketAckWindowReportsUnavoidableSupplyGapSeparatelyFromTail() {
        val regular=twoPacketWindow(0)
        val jitter=twoPacketWindow(272)
        println("TWO_PACKET ack_rtt_ms=20 pump_ms=17 fifo_frames=2400 regular_in_stream="+
            regular.inStreamMissing+" regular_tail="+regular.tailMissing+
            " jitter_in_stream="+jitter.inStreamMissing+" jitter_tail="+jitter.tailMissing)
        assertEquals(2,regular.maxPending);assertEquals(2,jitter.maxPending)
        assertEquals(0L,regular.inStreamMissing)
        assertTrue(jitter.inStreamMissing>0) // do not hide a genuine supply absence
        assertTrue(regular.tailMissing>0 && jitter.tailMissing>0)
    }
    @Test fun twoPrewrittenPacketsPauseNoiseResumeOrTrueInterruptWithoutResidualAudio() {
        for(interrupt in listOf(false,true)) {
            val native=FifoNative(4800);val acks=mutableListOf<PlaybackAck>()
            val player=Playback({native},{0L},acks::add)
            val packets=listOf(packet(0,2400),packet(2400,2400))
            player.bind(binding);packets.forEach {player.enqueue(it)};player.tick()
            assertEquals(4800,native.submitted.size) // pause AFTER both packets are submitted
            player.suspendOutput()
            repeat(5){assertEquals(0,native.consume());player.tick()}
            assertEquals(0L,native.position);assertTrue(acks.none {it.completed})
            if(interrupt) {
                player.stop()
                repeat(250){assertEquals(0,native.consume());player.tick()}
                assertEquals(0L,native.position);assertTrue(native.released)
                assertTrue(acks.none {it.completed})
            } else {
                player.resumeConfirmedNoise()
                repeat(200){assertEquals(24,native.consume());player.tick()}
                assertEquals(4800L,native.position)
                assertEquals(listOf("s0","s2400"),acks.filter {it.completed}.map {it.segment})
                assertEquals(4800,native.submitted.size) // no replay/duplicate writes
                player.stop()
            }
            assertTrue(packets.all {p->p.pcm.all {it==0.toShort()}})
        }
    }
    @Test fun jitterReplayPreservesExactWaveAndSeparatesInStreamFromTailStarvation() {
        val native=Native();val acks=mutableListOf<PlaybackAck>();var time=0L
        val player=Playback({native},{time},acks::add)
        player.bind(binding)
        val expected=mutableListOf<Short>();var next=0L
        // 100ms packets, including an explicit 272ms arrival gap; no hardware claim.
        val arrivals=listOf(0L,0L,0L,272L,292L,312L)
        var index=0;var inStreamMissing=0L;var tailMissing=0L
        for(ms in 0L..1100L) {
            time=ms
            while(index<arrivals.size && arrivals[index]<=ms) {
                val p=packet(next,if(index==arrivals.lastIndex)17 else 2400)
                expected.addAll(p.pcm.toList());next=p.end;player.enqueue(p);index++
            }
            if(ms%17L==0L) player.tick() // pump scheduling is deliberately not packet-aligned
            val wanted=24L
            val available=native.submitted.size-native.position
            val advance=minOf(wanted,available)
            native.position+=advance
            // Exclude the final partially occupied millisecond from in-stream starvation.
            if(native.position<12017L) inStreamMissing+=wanted-advance
            else tailMissing+=wanted-advance
        }
        player.tick()
        assertEquals(expected,native.submitted)
        assertEquals(6,acks.count {it.completed})
        assertFalse(player.hasPending)
        assertEquals(0L,inStreamMissing)
        assertTrue(tailMissing>0)
    }
}
