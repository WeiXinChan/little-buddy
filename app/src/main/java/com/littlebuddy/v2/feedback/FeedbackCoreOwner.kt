package com.littlebuddy.v2.feedback

import java.io.Closeable
import java.io.File
import java.nio.channels.FileChannel
import java.nio.channels.FileLock
import java.nio.channels.OverlappingFileLockException
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.StandardOpenOption

/** Held for the runtime/core lifetime, not an authorization lock. OS process death releases it.
 * Another process must refuse instead of constructing a second writer from an old snapshot. */
internal class FeedbackCoreOwner(private val file: File, private val vault: () -> FeedbackVault,
    private val clock: FeedbackClock, private val provider: FeedbackProvider = UnavailableFeedbackProvider) : Closeable {
    private var channel: FileChannel? = null
    private var lock: FileLock? = null
    @Synchronized fun open(authorizer: ParentAuthorizer): FeedbackCore {
        check(channel == null)
        var acquired: FileChannel? = null
        var lease: FileLock? = null
        try {
            require(!Files.isSymbolicLink(file.parentFile.toPath()))
            acquired = FileChannel.open(file.toPath(), StandardOpenOption.CREATE,
                StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS)
            lease = try { acquired.tryLock() } catch (_: OverlappingFileLockException) { null }
            if (lease == null) throw FeedbackFailure(Failure.STORAGE)
            val value = FeedbackCore(vault(), clock, authorizer, provider)
            channel = acquired; lock = lease
            return value
        } catch (failure: Exception) {
            try { lease?.release() } finally { acquired?.close() }
            throw if (failure is FeedbackFailure) failure else FeedbackFailure(Failure.STORAGE)
        }
    }
    // Runtime never reopens a live core. Tests/controlled process teardown close only after worker drain.
    @Synchronized override fun close() {
        try { lock?.release() } finally { channel?.close(); channel = null; lock = null }
    }
}
