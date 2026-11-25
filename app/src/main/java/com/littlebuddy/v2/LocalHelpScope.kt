package com.littlebuddy.v2

internal enum class LocalHelpReason { REVIEW_UNAVAILABLE, CONTENT_BLOCKED }
/** Scope is learned from ordinary open/bound, never from the failure which asks for help. */
internal class LocalHelpScope {
    private var session: String? = null
    private var turn = -1L
    private var epoch = -1L
    private var revision = -1L
    private var consumed = false
    fun bind(session: String, turn: Long, epoch: Long, revision: Long) {
        require(session.matches(Regex("[a-f0-9]{32}")) && turn >= 0 && epoch >= 0 && revision >= 0)
        if (session == this.session && turn == this.turn && epoch == this.epoch && revision == this.revision) return
        this.session = session; this.turn = turn; this.epoch = epoch; this.revision = revision; consumed = false
    }
    fun matches(session: String, turn: Long, epoch: Long, revision: Long) =
        session == this.session && turn == this.turn && epoch == this.epoch && revision == this.revision
    fun accept(session: String, turn: Long, epoch: Long, revision: Long,
        version: Int, prompt: String, reason: String): LocalHelpReason? {
        if (consumed || !matches(session, turn, epoch, revision) ||
            version != 1 || prompt != "safety_support_v1") return null
        val result = when (reason) {
            "review_unavailable" -> LocalHelpReason.REVIEW_UNAVAILABLE
            "content_blocked" -> LocalHelpReason.CONTENT_BLOCKED
            else -> return null
        }
        consumed = true; return result
    }
    fun clear() { session = null; turn = -1; epoch = -1; revision = -1; consumed = false }
}
