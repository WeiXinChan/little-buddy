package com.littlebuddy.v2.feedback

import java.nio.file.Files
import javax.crypto.KeyGenerator
import org.junit.Assert.*
import org.junit.Test

/** Uses independent reflection to observe retained arrays, not just submit-token rejection. */
class DraftExpiryTest {
    private class Clock(var time: Long = 1000) : FeedbackClock { override fun now() = time }
    private class Auth : ParentAuthorizer {
        var enabled = true
        var delegate: ParentAuthorizer? = null
        private object Intent : ParentIntent
        override fun prepare(operation: Operation, digest: String): ParentIntent? =
            if (delegate != null) delegate!!.prepare(operation, digest) else if (enabled) Intent else null
        override fun accept(intent: ParentIntent, operation: Operation, digest: String, acceptance: () -> Unit): Boolean {
            delegate?.let { return it.accept(intent, operation, digest, acceptance) }
            if (!enabled || intent !== Intent) return false
            acceptance(); return true
        }
    }
    private class Rig : AutoCloseable {
        val dir = Files.createTempDirectory("m09-draft-expiry-").toFile()
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val clock = Clock(); val auth = Auth()
        val core = FeedbackCore(FeedbackVault(PrivateVaultFiles(dir), key), clock, auth)
        fun record() { core.record(mapOf("stage" to LogStage.PLAY, "error" to LogError.NONE,
            "version" to 1, "elapsedMs" to 10L, "usage" to 1L)) }
        fun draft(): Any = FeedbackCore::class.java.getDeclaredField("draft").apply { isAccessible = true }.get(core)
        fun logs(): ByteArray = draft().javaClass.getDeclaredField("logs").apply { isAccessible = true }.get(draft()) as ByteArray
        fun revision(): Long = FeedbackCore::class.java.getDeclaredField("revision").apply { isAccessible = true }.getLong(core)
        fun confirmation(): Any? = FeedbackCore::class.java.getDeclaredField("confirmation").apply { isAccessible = true }.get(core)
        fun description(): String = draft().javaClass.getDeclaredField("description").apply { isAccessible = true }.get(draft()) as String
        fun select(): Confirmation {
            core.startDraft(Category.OTHER, "synthetic parent description")
            core.selectLogs(0, clock.time)
            return core.preview()
        }
        override fun close() { dir.deleteRecursively() }
    }
    @Test fun beforeExactAndAfterExpiryObserveOldBufferZeroing() {
        for (offset in listOf(-1L, 0L, 1L)) Rig().use { r ->
            r.record(); r.select(); val old = r.logs(); val original = old.copyOf()
            r.clock.time += WEEK + offset; r.core.sweep()
            if (offset < 0) { assertArrayEquals(original, old); assertArrayEquals(original, r.logs()); assertNotNull(r.confirmation()) }
            else { assertTrue(r.logs().isEmpty()); assertTrue(old.all { it == 0.toByte() }); assertNull(r.confirmation()) }
        }
    }
    @Test fun revokedParentCannotPreventSystemExpiry() = Rig().use { r ->
        r.record(); r.select(); val old = r.logs(); r.auth.enabled = false
        r.clock.time += WEEK; r.core.sweep()
        assertTrue(r.logs().isEmpty()); assertTrue(old.all { it == 0.toByte() }); assertNull(r.confirmation())
    }
    @Test fun noParentAuthorizerNeededForSweep() = Rig().use { r ->
        r.record(); r.select(); val old = r.logs()
        r.auth.delegate = DenyParentAuthorizer
        r.clock.time += WEEK; r.core.sweep()
        assertTrue(old.all { it == 0.toByte() }); assertTrue(r.logs().isEmpty())
    }
    @Test fun expiryInvalidatesOriginalConfirmationWithoutPreview() = Rig().use { r ->
        r.record(); val token = r.select(); val revision = r.revision()
        r.clock.time += WEEK; r.core.sweep()
        assertTrue(r.revision() > revision); assertNull(r.confirmation())
        try { r.core.submit(token); fail("old confirmation must be stale") }
        catch (failure: FeedbackFailure) { assertEquals(Failure.STALE, failure.reason) }
    }
    @Test fun repeatedSweepDoesNotInvalidateUnchangedPureDescriptionAgain() = Rig().use { r ->
        r.record(); r.select(); r.clock.time += WEEK; r.core.sweep()
        val revision = r.revision(); repeat(3) { r.core.sweep() }
        assertEquals(revision, r.revision()); assertTrue(r.logs().isEmpty())
        assertEquals("synthetic parent description", r.description())
        val token = r.core.preview(); r.core.sweep()
        assertSame(token, r.confirmation()); assertEquals(0, token.logs.count)
    }
    @Test fun partlyExpiredRangeClearsAllSelectedCopiesButPreservesFreshSource() = Rig().use { r ->
        val base = r.clock.time; r.record(); r.clock.time += DAY; r.record()
        assertEquals(2, r.select().logs.count); val old = r.logs()
        r.clock.time = base + WEEK; r.core.sweep()
        assertTrue(old.all { it == 0.toByte() }); assertTrue(r.logs().isEmpty())
        val empty = r.core.preview().logs
        assertNull(empty.from); assertNull(empty.through); assertEquals(0, empty.count); assertEquals(0, empty.bytes)
        r.core.selectLogs(0, r.clock.time)
        assertEquals(1, r.core.preview().logs.count)
    }
    @Test fun replacedAndCancelledDraftArraysCannotEscapeExpiry() = Rig().use { r ->
        r.record(); r.select(); val first = r.logs()
        r.select(); val second = r.logs(); assertTrue(first.all { it == 0.toByte() })
        r.core.cancelDraft(); assertTrue(second.all { it == 0.toByte() })
        r.select(); val third = r.logs(); r.clock.time += WEEK; r.core.sweep()
        assertTrue(third.all { it == 0.toByte() }); assertTrue(r.logs().isEmpty())
    }
    @Test fun independentActiveDraftsExpireOnTheirOwnClockAndSweep() {
        Rig().use { first -> Rig().use { second ->
            first.record(); first.select(); val firstBytes = first.logs()
            second.record(); second.select(); val secondBytes = second.logs(); val original = secondBytes.copyOf()
            first.clock.time += WEEK; first.core.sweep()
            assertTrue(firstBytes.all { it == 0.toByte() }); assertArrayEquals(original, secondBytes)
            second.auth.enabled = false; second.clock.time += WEEK + 1; second.core.sweep()
            assertTrue(secondBytes.all { it == 0.toByte() }); assertTrue(second.logs().isEmpty())
        } }
    }
    @Test fun draftExpiryPreservesUnexpiredIssueAndDescription() {
        Review39Probe.Rig().use { r ->
            val base = r.c.t; r.record(); r.core.startDraft(Category.OTHER, "retained issue")
            r.c.t += DAY; r.core.submit(r.core.preview())
            r.core.startDraft(Category.OTHER, "retained draft"); r.core.selectLogs(0, r.c.t); r.core.preview()
            r.c.t = base + WEEK; r.core.sweep()
            assertEquals("retained issue", r.core.list().single().description)
            val field = FeedbackCore::class.java.getDeclaredField("draft").apply { isAccessible = true }
            val draft = field.get(r.core)
            assertEquals("retained draft", draft.javaClass.getDeclaredField("description").apply { isAccessible = true }.get(draft))
            assertEquals(0, r.core.preview().logs.count)
        }
    }
}
