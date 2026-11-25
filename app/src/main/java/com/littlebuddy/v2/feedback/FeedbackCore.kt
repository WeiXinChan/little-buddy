package com.littlebuddy.v2.feedback

import java.io.*
import java.util.UUID

/** Only numeric versions, bounded counters and enums reach disk. Never accept free-form log strings. */
enum class LogStage { CONNECT, RECOGNIZE, GENERATE, PLAY, CANCEL }
enum class LogError { NONE, TIMEOUT, OFFLINE, REJECTED, INTERNAL }
internal data class Event(val at: Long, val stage: LogStage, val error: LogError,
    val version: Int, val elapsed: Long, val usage: Long) {
    fun encoded() = "$at,${stage.name},${error.name},$version,$elapsed,$usage\n".toByteArray(Charsets.US_ASCII)
}
class LogPreview(val from: Long?, val through: Long?, val count: Int, val bytes: Int)
class Confirmation internal constructor(internal val revision: Long, internal val digest: String, val logs: LogPreview)
class FeedbackView(val id: String, val category: Category, val description: String?, val state: FeedbackState,
    val submittedAt: Long?, val deleteBy: Long, val reply: String?)
internal class Material(val id: String, val category: Category, var description: String, var logs: ByteArray,
    val created: Long, val logsUntil: Long, var submitted: Long? = null, var withdrawn: Long? = null,
    var state: FeedbackState = FeedbackState.PENDING, var reply: String = "") {
    fun expires() = deadline(submitted, withdrawn, created)
    fun redact() { description = ""; logs.fill(0); logs = byteArrayOf(); reply = "" }
}
private class AdmissionDecision(val key: String)
private class Draft(val category: Category, var description: String, var logs: ByteArray, var preview: LogPreview) {
    fun erase() { description = ""; logs.fill(0); logs = byteArrayOf() }
}

/** Offline product core. No synthetic authorizer/provider exists in main sources. */
class FeedbackCore(private val vault: FeedbackVault, private val clock: FeedbackClock,
    private val authorizer: ParentAuthorizer = DenyParentAuthorizer,
    private val provider: FeedbackProvider = UnavailableFeedbackProvider) {
    private var events = mutableListOf<Event>()
    private var materials = linkedMapOf<String, Material>()
    private var lastTime = 0L
    private var revision = 0L
    private var draft: Draft? = null
    private var confirmation: Confirmation? = null
    private var unhealthy = false
    init {
        val saved = vault.load()
        if (saved != null) {
            try { decode(saved) } catch (_: Exception) { throw FeedbackFailure(Failure.QUARANTINED) }
        }
        sweep()
    }
    private fun now(): Long {
        if (unhealthy) throw FeedbackFailure(Failure.QUARANTINED)
        val value = clock.now() ?: throw FeedbackFailure(Failure.CLOCK)
        if (value < lastTime || value < 0 || value > Long.MAX_VALUE - WEEK) throw FeedbackFailure(Failure.CLOCK)
        lastTime = value
        return value
    }
    private fun permit(op: Operation, scope: String) {
        val intent = authorizer.prepare(op, scope) ?: throw FeedbackFailure(Failure.DENIED)
        var accepted = false
        if (!authorizer.accept(intent, op, scope) { accepted = true } || !accepted)
            throw FeedbackFailure(Failure.DENIED)
    }
    private fun persist() {
        try { vault.save(encode()) } catch (failure: FeedbackFailure) {
            unhealthy = true
            draft?.erase(); draft = null; confirmation = null
            materials.values.forEach { it.redact() }
            throw failure
        }
    }
    /** Prepare on isolated maps, stage with an ephemeral key, then publish actual state in accept.
     * After publication, persistence is fulfilment of THIS transaction, never a reusable grant.
     * A crash/write failure at that point quarantines; no success is returned or upload replayed.
     */
    private fun protectedChange(op: Operation, scope: String, mutation: () -> Unit, publish: () -> Unit = {}) {
        val intent = authorizer.prepare(op, scope) ?: throw FeedbackFailure(Failure.DENIED)
        val oldEvents = events; val oldMaterials = materials
        val before = encode()
        val candidate: ByteArray
        val nextEvents: MutableList<Event>
        val nextMaterials: LinkedHashMap<String, Material>
        try {
            events = mutableListOf(); materials = linkedMapOf(); decode(before)
            mutation(); candidate = encode(); nextEvents = events; nextMaterials = materials
        } finally { events = oldEvents; materials = oldMaterials; before.fill(0) }
        val staged = vault.stage(candidate)
        var committed: FeedbackVault.Committed? = null
        try {
            authorizer.accept(intent, op, scope) {
                // Irreversible process-local commit point: a specific state/transaction is published.
                // No disk, network, crypto, decoding or callbacks under the authorization lock.
                committed = staged.decide()
                events = nextEvents; materials = nextMaterials
                publish()
            }
            val transaction = committed ?: throw FeedbackFailure(Failure.DENIED)
            try { transaction.persist() } catch (failure: FeedbackFailure) {
                unhealthy = true; draft?.erase(); draft = null; confirmation = null
                materials.values.forEach { it.redact() }; throw failure
            }
        } finally { staged.discard() }
    }
    private fun changed() { revision++; confirmation = null }

    /** Unknown fields are discarded before persistence; wrong-typed values cannot inject strings. */
    @Synchronized fun record(fields: Map<String, Any?>) {
        val time = now()
        val stage = fields["stage"] as? LogStage ?: return
        val error = fields["error"] as? LogError ?: return
        val version = fields["version"] as? Int ?: return
        val elapsed = fields["elapsedMs"] as? Long ?: return
        val usage = fields["usage"] as? Long ?: return
        if (version !in 1..1_000_000 || elapsed !in 0..DAY || usage !in 0..1_000_000_000L) return
        events.removeAll { time >= it.at + WEEK }
        events.add(Event(time, stage, error, version, elapsed, usage))
        while (events.size > 1000 || events.sumOf { it.encoded().size } > 256 * 1024) events.removeAt(0)
        persist()
    }
    @Synchronized fun startDraft(category: Category, description: String) {
        now(); permit(Operation.DRAFT, "draft")
        validateText(description)
        draft?.erase()
        draft = Draft(category, description, byteArrayOf(), LogPreview(null, null, 0, 0))
        changed()
    }
    @Synchronized fun editDescription(description: String) {
        now(); permit(Operation.DRAFT, "draft"); validateText(description)
        (draft ?: throw FeedbackFailure(Failure.INVALID)).description = description
        changed()
    }
    @Synchronized fun selectLogs(from: Long, through: Long) {
        val time = now(); permit(Operation.DRAFT, "draft")
        if (from < 0 || through < from || through > time) throw FeedbackFailure(Failure.INVALID)
        val current = draft ?: throw FeedbackFailure(Failure.INVALID)
        val chosen = events.filter { it.at in from..through && time < it.at + WEEK }
        current.logs.fill(0)
        current.logs = chosen.fold(byteArrayOf()) { bytes, event -> bytes + event.encoded() }
        current.preview = LogPreview(chosen.firstOrNull()?.at, chosen.lastOrNull()?.at, chosen.size, current.logs.size)
        changed()
    }
    @Synchronized fun withoutLogs() {
        now(); permit(Operation.DRAFT, "draft")
        val current = draft ?: throw FeedbackFailure(Failure.INVALID)
        current.logs.fill(0); current.logs = byteArrayOf(); current.preview = LogPreview(null, null, 0, 0)
        changed()
    }
    @Synchronized fun preview(): Confirmation {
        val time = now(); permit(Operation.READ, "draft")
        val current = draft ?: throw FeedbackFailure(Failure.INVALID)
        if (current.preview.from?.let { time >= it + WEEK } == true) { withoutLogs() }
        return Confirmation(revision, draftDigest(current), current.preview).also { confirmation = it }
    }
    @Synchronized fun cancelDraft() { draft?.erase(); draft = null; changed() }
    private fun draftDigest(current: Draft) = digest(
        "${current.category.name}\u0000${current.description}\u0000".toByteArray() + current.logs)
    private fun validateText(text: String) {
        if (text.isBlank() || text.codePointCount(0, text.length) > 2000) throw FeedbackFailure(Failure.INVALID)
    }

    /** No automatic resend on restart. A confirmed payload is staged, then grant revalidated at admission. */
    fun submit(token: Confirmation): String {
        val id: String
        val payload: FeedbackPayload
        val transportIntent: ParentIntent
        synchronized(this) {
            val time = now()
            val current = draft ?: throw FeedbackFailure(Failure.STALE)
            if (token !== confirmation || token.revision != revision || token.digest != draftDigest(current) ||
                current.preview.from?.let { time >= it + WEEK } == true) throw FeedbackFailure(Failure.STALE)
            transportIntent = authorizer.prepare(Operation.SUBMIT, token.digest) ?: throw FeedbackFailure(Failure.DENIED)
            if (!provider.available()) throw FeedbackFailure(Failure.UNAVAILABLE)
            if (materials.size >= 64) throw FeedbackFailure(Failure.INVALID)
            id = UUID.randomUUID().toString()
            payload = FeedbackPayload(current.category, current.description, current.logs.copyOf())
            protectedChange(Operation.SUBMIT, token.digest, {
                materials[id] = Material(id, current.category, current.description, current.logs.copyOf(), time, current.preview.from?.plus(WEEK) ?: time)
            }, { cancelDraft() })
        }
        try {
            val receipt = provider.submit(id, payload) {
                synchronized(this) {
                    val time = now()
                    val entry = materials[id]
                    if (entry == null || entry.withdrawn != null || time >= entry.expires()) false
                    else {
                        var decision: AdmissionDecision? = null
                        authorizer.accept(transportIntent, Operation.SUBMIT, token.digest) {
                            decision = AdmissionDecision(id)
                        }
                        decision?.key == id
                    }
                }
            }
            synchronized(this) {
                val time = now()
                val entry = materials[id]
                // Late success never resurrects a withdrawn/expired record. Original key deletion survives.
                if (entry != null) {
                    if (receipt.submittedAt < entry.created || receipt.submittedAt > time)
                        throw FeedbackFailure(Failure.INVALID)
                    if (time >= entry.expires() && entry.withdrawn == null) {
                        entry.withdrawn = minOf(time, entry.expires()); entry.redact()
                    }
                    if (entry.submitted == null) entry.submitted = receipt.submittedAt
                    if (entry.withdrawn == null && time < entry.expires()) entry.state = FeedbackState.SUBMITTED
                    else { entry.redact(); entry.state = FeedbackState.DELETE_PENDING }
                    persist()
                }
            }
        } catch (_: Exception) {
            synchronized(this) {
                if (!unhealthy) materials[id]?.let {
                    if (it.withdrawn == null) it.state = FeedbackState.SEND_FAILED
                    persist()
                }
            }
        } finally { payload.logs.fill(0) }
        return id
    }
    /** Retries of ambiguous uploads must use the same key; only deletion is replayed automatically. */
    @Synchronized fun withdraw(id: String) {
        val time = now()
        if (materials[id] == null) return
        protectedChange(Operation.WITHDRAW, id, {
            val entry = materials.getValue(id)
            if (entry.withdrawn == null) entry.withdrawn = time
            entry.redact(); entry.state = FeedbackState.DELETE_PENDING
        }) // durable intent before provider call; failure is explicit, never 'deleted'
    }
    /** System deletion does not need a live parent grant and cannot submit new material. */
    fun drainDeletions() {
        val keys = synchronized(this) { now(); materials.values.filter { it.withdrawn != null }.map { it.id } }
        for (id in keys) {
            try {
                if (!provider.available()) throw FeedbackFailure(Failure.UNAVAILABLE)
                val receipt = provider.withdraw(id)
                synchronized(this) {
                    val time = now()
                    materials[id]?.let {
                        if (receipt.receivedAt < it.created || receipt.receivedAt > time)
                            throw FeedbackFailure(Failure.INVALID)
                        it.withdrawn = minOf(it.withdrawn!!, receipt.receivedAt)
                        it.state = if (receipt.allCopiesDeleted) FeedbackState.DELETED else FeedbackState.DELETING
                        persist()
                    }
                }
            } catch (_: Exception) {
                synchronized(this) {
                    if (!unhealthy) materials[id]?.let { it.state = FeedbackState.DELETE_FAILED; persist() }
                }
            }
        }
    }
    @Synchronized fun list(): List<FeedbackView> {
        sweep()
        val time = now(); permit(Operation.READ, "list")
        return materials.values.filter { time < (it.submitted?.plus(WEEK) ?: (it.created + WEEK)) }.map {
            val visible = it.withdrawn == null && time < it.expires()
            FeedbackView(it.id, it.category, if (visible) it.description else null, it.state,
                it.submitted, it.expires(), if (visible) it.reply else null)
        }
    }
    /** Reply/supplement protocol never changes original timestamps. Not wired to an unreviewed server. */
    @Synchronized internal fun receiveReply(id: String, text: String) {
        val time = now(); validateText(text)
        val entry = materials[id] ?: return
        if (entry.withdrawn != null || time >= entry.expires()) return
        entry.reply = text; entry.state = FeedbackState.REPLIED; persist()
    }
    @Synchronized fun clearLogs() {
        now()
        protectedChange(Operation.CLEAR_LOGS, "source-logs", { events.clear() }, {
            draft?.let { it.logs.fill(0); it.logs = byteArrayOf(); it.preview = LogPreview(null, null, 0, 0) }
            changed()
        }) // only source logs, never submitted copies, PIN or pairing
    }
    @Synchronized fun sweep() {
        val time = now()
        events.removeAll { time >= it.at + WEEK }
        materials.values.forEach {
            if (time >= it.logsUntil) { it.logs.fill(0); it.logs = byteArrayOf() }
            if (time >= it.expires() && it.withdrawn == null) {
                it.withdrawn = time; it.state = FeedbackState.DELETE_PENDING; it.redact()
            }
        }
        // Keep only a payload-free deletion task until the ORIGINAL retention ceiling.
        materials.entries.removeAll { (_, it) -> time >= (it.submitted?.plus(WEEK) ?: (it.created + WEEK)) }
        persist()
    }
    private fun encode(): ByteArray = ByteArrayOutputStream().also { buffer ->
        DataOutputStream(buffer).use { out ->
            out.writeInt(1); out.writeLong(lastTime); out.writeInt(events.size)
            events.forEach { out.writeLong(it.at); out.writeUTF(it.stage.name); out.writeUTF(it.error.name)
                out.writeInt(it.version); out.writeLong(it.elapsed); out.writeLong(it.usage) }
            out.writeInt(materials.size)
            materials.values.forEach { out.writeUTF(it.id); out.writeUTF(it.category.name); out.writeUTF(it.description)
                out.writeInt(it.logs.size); out.write(it.logs); out.writeLong(it.created); out.writeLong(it.logsUntil)
                out.writeLong(it.submitted ?: -1); out.writeLong(it.withdrawn ?: -1)
                out.writeUTF(it.state.name); out.writeUTF(it.reply) }
        }
    }.toByteArray()
    private fun decode(bytes: ByteArray) {
        DataInputStream(ByteArrayInputStream(bytes)).use { input ->
            require(input.readInt() == 1); lastTime = input.readLong(); require(lastTime >= 0)
            val count = input.readInt(); require(count in 0..1000)
            repeat(count) { events.add(Event(input.readLong(), LogStage.valueOf(input.readUTF()),
                LogError.valueOf(input.readUTF()), input.readInt(), input.readLong(), input.readLong())) }
            val size = input.readInt(); require(size in 0..64)
            repeat(size) {
                val id = input.readUTF(); require(id.length == 36 && id !in materials)
                val category = Category.valueOf(input.readUTF()); val description = input.readUTF()
                val logSize = input.readInt(); require(logSize in 0..256 * 1024)
                val logs = ByteArray(logSize); input.readFully(logs)
                val created = input.readLong(); val logsUntil = input.readLong(); val submitted = input.readLong().takeIf { it >= 0 }
                val withdrawn = input.readLong().takeIf { it >= 0 }
                require(created >= 0 && created <= lastTime && (submitted == null || submitted in created..lastTime))
                require(withdrawn == null || withdrawn in created..lastTime)
                val state = FeedbackState.valueOf(input.readUTF()); val reply = input.readUTF()
                require(description.codePointCount(0, description.length) <= 2000 && reply.codePointCount(0, reply.length) <= 2000)
                materials[id] = Material(id, category, description, logs, created, logsUntil, submitted, withdrawn, state, reply)
            }
            require(input.available() == 0)
        }
    }
}
