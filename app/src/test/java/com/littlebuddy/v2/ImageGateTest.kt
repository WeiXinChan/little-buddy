package com.littlebuddy.v2

import org.junit.Assert.*
import org.junit.Test

class ImageGateTest {
    private val scope = ImageScope("a".repeat(32), 2, 3, 4)
    private val asset = ImageAsset("cloud-dragon", "b".repeat(64), 512, 512)
    private val ready = ImageReady(scope, 8, "12345678123412341234123456789abc", asset)
    private val reveal = ImageReveal(ready, "player", 6, "last", 2400)
    private fun gate() = ImageGate<String> {}.also { it.bind(scope) }
    private fun ack(g: ImageGate<String>) = g.acknowledged("player", 6, "last", 2400)
    private fun visible(g: ImageGate<String>): String? { var value: String? = null; g.render { value = it }; return value }
    @Test fun readyOnlyRemainsPrivateIncludingFutureTopic() {
        val g = gate(); val ticket = g.prepare(ready)!!; g.loaded(ticket, "bitmap")
        assertNull(visible(g)); assertEquals(8, ready.topic)
    }
    @Test fun onlyFullExactAckRevealsOnce() {
        val g = gate(); val ticket = g.prepare(ready)!!; g.loaded(ticket, "bitmap")
        g.acknowledged("player", 6, "last", 2399)
        assertFalse(g.reveal(reveal)); assertNull(visible(g)); ack(g)
        assertTrue(g.reveal(reveal)); assertEquals("bitmap", visible(g)); assertFalse(g.reveal(reveal))
    }
    @Test fun revealBeforeLoadWaitsPrivatelyThenPublishes() {
        val g = gate(); val ticket = g.prepare(ready)!!; ack(g)
        assertTrue(g.reveal(reveal)); assertNull(visible(g)); g.loaded(ticket, "bitmap"); assertEquals("bitmap", visible(g))
    }
    @Test fun loadBeforeAckAlsoWorks() {
        val g = gate(); ack(g); val ticket = g.prepare(ready)!!; g.loaded(ticket, "bitmap")
        assertNull(visible(g)); assertTrue(g.reveal(reveal)); assertEquals("bitmap", visible(g))
    }
    @Test fun everyAckCoordinateMustMatch() {
        for (wrong in listOf(reveal.copy(player="other"), reveal.copy(stream=7), reveal.copy(segment="first"), reveal.copy(end=2399))) {
            val g = gate(); g.loaded(g.prepare(ready)!!, "bitmap"); ack(g)
            assertFalse(g.reveal(wrong)); assertNull(visible(g))
        }
    }
    @Test fun scopeTopicTokenAndHashAllMatch() {
        val wrong = listOf(ready.copy(scope=scope.copy(session="c".repeat(32))), ready.copy(scope=scope.copy(turn=3)),
            ready.copy(scope=scope.copy(epoch=4)), ready.copy(scope=scope.copy(revision=5)), ready.copy(topic=9),
            ready.copy(token="22345678123412341234123456789abc"), ready.copy(asset=asset.copy(sha256="c".repeat(64))),
            ready.copy(asset=asset.copy(id="garden")))
        for (value in wrong) { val g=gate(); g.loaded(g.prepare(ready)!!,"bitmap"); ack(g)
            assertFalse(g.reveal(reveal.copy(ready=value))); assertNull(visible(g)) }
    }
    @Test fun clearRejectsLateLoadAckAndReveal() {
        val g=gate(); val t=g.prepare(ready)!!; ack(g); g.clear(); g.loaded(t,"old"); ack(g)
        assertFalse(g.reveal(reveal)); assertNull(g.prepare(ready)); assertNull(visible(g))
    }
    @Test fun newConnectionEvenSameWireScopeCannotBorrowOldLoadOrAck() {
        val g=gate(); val t=g.prepare(ready)!!; ack(g); g.clear(); g.bind(scope)
        val fresh=g.prepare(ready)!!; g.loaded(t,"old"); assertNull(visible(g)); assertFalse(g.reveal(reveal))
        g.loaded(fresh,"fresh"); ack(g); assertTrue(g.reveal(reveal)); assertEquals("fresh",visible(g))
    }
    @Test fun replacementCannotReviveOlderToken() {
        val g=gate(); val old=g.prepare(ready)!!; val newer=ready.copy(token="22345678123412341234123456789abc")
        g.prepare(newer); g.loaded(old,"old"); ack(g); assertFalse(g.reveal(reveal)); assertNull(g.prepare(ready)); assertNull(visible(g))
    }
    @Test fun failedDecodeRemainsHiddenAndRejectsLateSuccess() {
        val g=gate(); val t=g.prepare(ready)!!; ack(g); g.failed(t); g.loaded(t,"old")
        assertFalse(g.reveal(reveal)); assertNull(g.prepare(ready)); assertNull(visible(g))
    }
    @Test fun publicationRechecksAfterQueuedUiCallback() {
        var scheduled=0; val g=ImageGate<String> { scheduled++ }; g.bind(scope)
        g.loaded(g.prepare(ready)!!,"bitmap"); ack(g); assertTrue(g.reveal(reveal)); assertTrue(scheduled>0)
        g.clear(); assertNull(visible(g)) // queued UI render observes clear, not a captured bitmap
    }
    @Test fun newRevisionRejectsOldPreparation() {
        val g=gate(); g.bind(scope.copy(revision=5)); assertNull(g.prepare(ready))
        assertNull(g.prepare(ready.copy(scope=scope.copy(revision=5), token="bad")))
    }
}
