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
