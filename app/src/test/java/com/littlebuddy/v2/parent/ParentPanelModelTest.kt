package com.littlebuddy.v2.parent

import org.junit.Assert.*
import org.junit.Test
import java.util.ArrayDeque

class ParentPanelModelTest {
    private class Store : ParentStore {
        var bytes: ByteArray? = null
        override fun read() = bytes?.let(ParentCodec::decode)
        override fun write(record: ParentRecord, authorized: () -> Boolean) {
            check(authorized()); bytes = ParentCodec.encode(record)
        }
    }
    private class Rig(owned: Boolean = true, configured: Boolean = true) {
        val store = Store(); var time = 100L
        val domain = ParentDomain(store, { time }, {}, object : OwnerProof {
            override fun consume(challenge: OwnerChallenge) = true
        }, "panel-test")
        val work = ArrayDeque<() -> Unit>(); val ui = ArrayDeque<() -> Unit>()
        val rendered = mutableListOf<PanelState>(); var exits = 0
        val model = ParentPanelModel({ if (configured) domain else null }, { work.add(it) }, { ui.add(it) },
            { rendered.add(it) }, { exits++ })
        init {
            if (owned) {
                val page = domain.enterPage()
                check(domain.replacePin("012345".toCharArray(), domain.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN, page)!!, page))
            }
        }
        fun drain() { while (work.isNotEmpty() || ui.isNotEmpty()) { while (work.isNotEmpty()) work.removeFirst()(); while (ui.isNotEmpty()) ui.removeFirst()() } }
        fun open() { model.open(); drain() }
        fun unlock() { open(); model.verify("012345".toCharArray()); drain(); assertEquals(PanelMode.SETTINGS, model.state.mode) }
    }
    @Test fun noBindingAndNoOwnerNeverOfferInitialization() {
        val unavailable = Rig(configured = false); unavailable.open()
        assertEquals(PanelMode.UNAVAILABLE, unavailable.model.state.mode)
        val fresh = Rig(owned = false); fresh.open()
        assertEquals(PanelNotice.UNOWNED, fresh.model.state.notice)
        val pin = "012345".toCharArray(); fresh.model.verify(pin); fresh.drain()
        assertNull(fresh.store.bytes); assertTrue(pin.all { it == '\u0000' })
    }
    @Test fun displayedSettingsUseActualGrantAndPersistedValue() {
        val r = Rig(); r.unlock(); r.model.saveVolume(75); r.drain()
        assertEquals(75, r.store.read()!!.volumeLimit); assertEquals(PanelNotice.SAVED, r.model.state.notice)
    }
    @Test fun beforeVerificationConfigurationAndNavigationReject() {
        val r = Rig(); r.open(); r.model.saveVolume(90); assertNull(r.model.navigate(PanelMode.CHANGE_PIN)); r.drain()
        assertEquals(60, r.store.read()!!.volumeLimit)
    }
    @Test fun staleRenderedButtonDoesNotActWithNewGrant() {
        val r = Rig(); r.unlock(); val oldView = r.model.viewToken
        r.model.navigate(PanelMode.CHANGE_PIN); r.model.navigate(PanelMode.SETTINGS)
        assertFalse(r.model.userAction(oldView) { r.model.saveVolume(90) }); r.drain()
        assertEquals(60, r.store.read()!!.volumeLimit)
    }
    @Test fun homeBeforeQueuedVerificationWipesPinAndRejectsLateResult() {
        val r = Rig(); r.open(); val pin = "012345".toCharArray(); r.model.verify(pin)
        r.model.pause(); assertTrue(pin.all { it == '\u0000' }); r.drain()
        assertEquals(PanelMode.VERIFY, r.model.state.mode); assertEquals(0, r.store.read()!!.failures)
    }
    @Test fun homeAfterVerificationBeforeUiResultDoesNotExposeSettings() {
        val r = Rig(); r.open(); r.model.verify("012345".toCharArray()); r.work.removeFirst()()
        r.model.pause(); r.drain(); assertEquals(PanelMode.VERIFY, r.model.state.mode)
        assertEquals(ParentDomain.State.LOCKED, r.domain.state())
    }
    @Test fun homeBeforeQueuedSaveRejectsWriteAndDoesNotRefreshScreen() {
        val r = Rig(); r.unlock(); r.model.saveVolume(90); r.model.pause(); r.drain()
        assertEquals(60, r.store.read()!!.volumeLimit); assertEquals(PanelMode.VERIFY, r.model.state.mode)
    }
    @Test fun idlePollingNeverRenewsAndExactBoundaryLocks() {
        val r = Rig(); r.unlock(); r.time += 119_999; r.model.tick()
        assertEquals(PanelMode.SETTINGS, r.model.state.mode); r.time++; r.model.tick()
        assertEquals(PanelMode.VERIFY, r.model.state.mode); assertEquals(PanelNotice.LOCKED, r.model.state.notice)
    }
    @Test fun validLocalTouchRenewsButBackgroundRouteCallbackDoesNot() {
        val r = Rig(); r.unlock(); r.time += 100_000; r.model.localTouch()
        r.time += 100_000; r.model.tick(); assertEquals(PanelMode.SETTINGS, r.model.state.mode)
        val route = r.model.navigate(PanelMode.FEEDBACK)!!
        r.time += 119_999; r.model.routeExit(route.revision)
        r.time++; r.model.tick(); assertEquals(PanelMode.VERIFY, r.model.state.mode)
    }
    @Test fun oldRouteCannotExitOrCommitIntoNewPage() {
        val r = Rig(); r.unlock(); val old = r.model.navigate(PanelMode.FEEDBACK)!!
        r.model.routeExit(old.revision); r.model.navigate(PanelMode.CHANGE_PIN)
        r.model.routeExit(old.revision)
        assertEquals(PanelMode.CHANGE_PIN, r.model.state.mode)
        assertFalse(old.domain.acceptProtected(old.grant) { fail() })
    }
    @Test fun pinChangeWipesInputsAndRequiresNewPinAfterCommit() {
        val r = Rig(); r.unlock(); r.model.navigate(PanelMode.CHANGE_PIN)
        val first = "123456".toCharArray(); val second = first.copyOf()
        r.model.changePin(first, second); assertTrue(second.all { it == '\u0000' }); r.drain()
        assertTrue(first.all { it == '\u0000' }); assertEquals(PanelNotice.PIN_CHANGED, r.model.state.notice)
        r.model.verify("123456".toCharArray()); r.drain(); assertEquals(PanelMode.SETTINGS, r.model.state.mode)
    }
    @Test fun mismatchedPinChangeDoesNotWriteOrQueue() {
        val r = Rig(); r.unlock(); r.model.navigate(PanelMode.CHANGE_PIN); val before = r.store.bytes!!.copyOf()
        val a = "123456".toCharArray(); val b = "123455".toCharArray(); r.model.changePin(a, b)
        assertTrue(a.all { it == '\u0000' }); assertTrue(b.all { it == '\u0000' }); assertTrue(r.work.isEmpty())
        assertArrayEquals(before, r.store.bytes)
    }
    @Test fun fiveFailuresSurviveNewPanelAndCooldownIsVisible() {
        val r = Rig(); r.open()
        repeat(5) { r.model.verify("999999".toCharArray()); r.drain() }
        assertEquals(PanelNotice.COOLDOWN, r.model.state.notice)
        r.model.pause(); r.open(); assertEquals(PanelNotice.COOLDOWN, r.model.state.notice)
        r.time += 60_000; r.model.tick(); assertEquals(PanelNotice.NONE, r.model.state.notice)
    }
    @Test fun cancelAndDestroySuppressLoaderAndAllOldCallbacks() {
        val r = Rig(); r.model.open(); r.model.exit(); r.drain()
        assertEquals(1, r.exits); assertFalse(r.rendered.any { it.mode == PanelMode.SETTINGS })
        r.open(); r.model.verify("012345".toCharArray()); r.model.close(); r.drain()
        assertFalse(r.rendered.any { it.mode == PanelMode.SETTINGS })
    }
    @Test fun recoveryUnavailableDoesNotModifyPinOrPairing() {
        val r = Rig(); r.open(); val before = r.store.bytes!!.copyOf(); r.model.recoveryHelp()
        assertEquals(PanelNotice.RECOVERY_UNAVAILABLE, r.model.state.notice); assertArrayEquals(before, r.store.bytes)
    }
    @Test fun destroyingAnOldHostDoesNotRevokeALaterHost() {
        val r = Rig(); r.unlock(); r.model.pause()
        val later = ParentPanelModel({ r.domain }, { r.work.add(it) }, { r.ui.add(it) }, {}, {})
        later.open(); r.drain(); later.verify("012345".toCharArray()); r.drain()
        assertEquals(ParentDomain.State.AUTHORIZED, r.domain.state())
        r.model.close(); assertEquals(ParentDomain.State.AUTHORIZED, r.domain.state())
        later.close(); assertEquals(ParentDomain.State.LOCKED, r.domain.state())
    }
}
