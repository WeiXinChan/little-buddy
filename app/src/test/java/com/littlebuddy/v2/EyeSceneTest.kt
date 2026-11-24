package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
class EyeSceneTest {
    @Test fun cancellationAndManagementRejectQueuedWork() {
        val scene = EyeScene()
        val old = scene.event("speaking")
        scene.enter()
        assertFalse(scene.accepts(old))
        scene.event("listening")
        assertTrue(scene.management)
        scene.exit()
        assertEquals(EyeMood.WAKE, scene.mood)
        assertFalse(scene.accepts(old))
        assertTrue(scene.accepts(scene.generation))
    }
    @Test fun sleepClearsPendingInputAndDeadline() {
        var now = 0L
        var effects = 0
        val gate = InputGate(Waits(), { now }, { effects++ }, { effects++ }, { effects++ }, { effects++ }, { effects++ }, { effects++ })
        gate.wake(); gate.speech(); gate.quiet()
        gate.sleep(); val before = effects
        now = 30000; gate.checkResponseDeadline(); gate.tick(false)
        assertEquals(before, effects)
        gate.wake(); assertTrue(gate.awake)
    }
}
