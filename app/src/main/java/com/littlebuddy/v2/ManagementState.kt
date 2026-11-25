package com.littlebuddy.v2

internal data class ManagementScope(val session: String, val turn: Long, val epoch: Long, val revision: Long)
internal data class ManagementRequest(val scope: ManagementScope, val receipt: String? = null)

/** Audio owner only. A receipt is transport suspension authority, never a ParentDomain Grant.
 * No scope is learned from failure/state frames; bootstrap must be a requested normal scope response.
 */
internal class ManagementState(private val now: () -> Long) {
    enum class Phase { CHILD, SCOPE, PAUSING, PAUSED, RESUMING, WAITING_WAKE, DEAD }
    var phase = Phase.CHILD; private set
    val mediaAllowed get() = phase == Phase.CHILD
    private var scope: ManagementScope? = null
    private var expected: ManagementScope? = null
    private var receipt: String? = null
    private var deadline = Long.MAX_VALUE
    private var lastNow = 0L
    private fun time(): Long { val t=now(); check(t >= lastNow); lastNow=t; return t }
    fun normal(value: ManagementScope) {
        if (phase != Phase.CHILD) return
        require(value.session.matches(Regex("[a-f0-9]{32}")) && value.turn>=0 && value.epoch>=0 && value.revision>=0)
        scope=value // Only an ordinary current open/bound may establish a new participant's session.
    }
    fun begin(epoch: Long, revision: Long) {
        check(phase == Phase.CHILD || phase == Phase.WAITING_WAKE)
        phase=Phase.SCOPE; expected=ManagementScope(scope?.session ?: "", scope?.turn ?: -1, epoch, revision)
        receipt=null; deadline=time()+4000
    }
    fun scoped(value: ManagementScope): ManagementRequest? {
        val prior=expected ?: return null
        if (phase != Phase.SCOPE || time() >= deadline || value.epoch != prior.epoch || value.revision != prior.revision ||
            !value.session.matches(Regex("[a-f0-9]{32}")) || value.turn < 0 ||
            (prior.session.isNotEmpty() && value.session != prior.session)) return null
        scope=value
        val next=value.copy(epoch=value.epoch+1,revision=value.revision+1)
        expected=next; phase=Phase.PAUSING; deadline=time()+4000
        return ManagementRequest(next)
    }
    fun paused(value: ManagementScope, token: String): Boolean {
        if (phase != Phase.PAUSING || value != expected || time() >= deadline ||
            !token.matches(Regex("[a-f0-9]{32}"))) return false
        scope=value; receipt=token; phase=Phase.PAUSED; deadline=Long.MAX_VALUE; return true
    }
    fun resume(): ManagementRequest? {
        if (phase != Phase.PAUSED) return null
        val token=receipt ?: return null; receipt=null
        val current=scope ?: return null
        val next=current.copy(epoch=current.epoch+1,revision=current.revision+1)
        expected=next; phase=Phase.RESUMING; deadline=time()+4000
        return ManagementRequest(next,token)
    }
    fun waiting(value: ManagementScope): Boolean {
        if (phase != Phase.RESUMING || value != expected || time() >= deadline) return false
        scope=value; expected=null; phase=Phase.WAITING_WAKE; deadline=Long.MAX_VALUE; return true
    }
    fun wake(): Boolean {
        if (phase != Phase.WAITING_WAKE && phase != Phase.CHILD) return false
        phase=Phase.CHILD; return true
    }
    fun checkDeadline() { if (phase !in setOf(Phase.CHILD,Phase.PAUSED,Phase.WAITING_WAKE,Phase.DEAD)) check(time()<deadline) }
    fun close() { phase=Phase.DEAD; receipt=null; scope=null; expected=null; deadline=0 }
}
