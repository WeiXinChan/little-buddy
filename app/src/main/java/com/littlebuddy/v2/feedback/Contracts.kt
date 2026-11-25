package com.littlebuddy.v2.feedback

import java.security.MessageDigest

internal const val DAY = 86_400_000L
internal const val HOUR = 3_600_000L
internal const val WEEK = 7 * DAY

/** A clock losing trust must return null; wall time rollback is rejected by the store. */
fun interface FeedbackClock { fun now(): Long? }
enum class Operation { DRAFT, READ, SUBMIT, WITHDRAW, CLEAR_LOGS, CLEAR_LOCAL }
enum class Failure { DENIED, UNAVAILABLE, STORAGE, QUARANTINED, CLOCK, STALE, INVALID, NETWORK }
class FeedbackFailure(val reason: Failure) : Exception(reason.name)

/** Opaque process-local capability; never serialize a Grant or accept a client boolean. */
interface ParentIntent
interface ParentAuthorizer {
    fun prepare(operation: Operation, digest: String): ParentIntent?
    /**
     * Must revalidate exact scope, instance identity, page epoch, generation and idle time.
     * acceptance is a short in-memory publication only. No IO under the authorization lock.
     * HOME/revoke must not wait for storage, crypto, networking or provider callbacks.
     */
    fun accept(intent: ParentIntent, operation: Operation, digest: String, acceptance: () -> Unit): Boolean
}
object DenyParentAuthorizer : ParentAuthorizer {
    override fun prepare(operation: Operation, digest: String): ParentIntent? = null
    override fun accept(intent: ParentIntent, operation: Operation, digest: String, acceptance: () -> Unit) = false
}

enum class Category { RECOGNITION, CONVERSATION, INTERRUPT, SOUND_NETWORK, IMAGE, OTHER }
enum class FeedbackState { PENDING, SEND_FAILED, SUBMITTED, PROCESSING, REPLIED, DELETE_PENDING, DELETING, DELETE_FAILED, DELETED }
/** Payload is deliberately not a data class: toString must never print user text. */
class FeedbackPayload(val category: Category, val description: String, val logs: ByteArray)
class SubmitReceipt(val submittedAt: Long, val deleteBy: Long? = null)
class DeleteReceipt(val receivedAt: Long, val allCopiesDeleted: Boolean)

class FeedbackRemote(val submittedAt: Long?, val deleteBy: Long, val state: FeedbackState, val reply: String)
interface FeedbackProvider {
    fun binding(): String? = null
    fun submitAdmitted(key: String, payload: FeedbackPayload, binding: String?, admit: (() -> Unit) -> Boolean): SubmitReceipt =
        submit(key,payload) { admit {} }
    fun withdrawBound(key: String, binding: String?): DeleteReceipt = withdraw(key)
    fun read(key: String, binding: String?, admit: (() -> Unit) -> Boolean): FeedbackRemote = throw FeedbackFailure(Failure.UNAVAILABLE)

    /** Unreviewed D02/D06 providers must return false. No network credentials in this domain. */
    fun available(): Boolean
    /** The reviewed adapter must enforce device binding and a final grant check at admission. */
    fun submit(idempotencyKey: String, payload: FeedbackPayload, admit: () -> Boolean): SubmitReceipt
    /** Delete by the original key even if upload timed out before returning an ID. */
    fun withdraw(idempotencyKey: String): DeleteReceipt
}
object UnavailableFeedbackProvider : FeedbackProvider {
    override fun available() = false
    override fun submit(idempotencyKey: String, payload: FeedbackPayload, admit: () -> Boolean): SubmitReceipt =
        throw FeedbackFailure(Failure.UNAVAILABLE)
    override fun withdraw(idempotencyKey: String): DeleteReceipt = throw FeedbackFailure(Failure.UNAVAILABLE)
}

internal fun digest(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
    .digest(bytes).joinToString("") { "%02x".format(it) }
internal fun deadline(submitted: Long?, withdrawn: Long?, created: Long): Long =
    minOf(submitted?.plus(WEEK) ?: (created + HOUR), withdrawn?.plus(DAY) ?: Long.MAX_VALUE)
