package com.littlebuddy.v2

/** One current transport scope, not a configuration Grant or a reusable Boolean permit. */
internal class ManagementEntry internal constructor(internal val scope: ManagementScope, internal val expiresAt: Long)
internal class ManagementEntryGate(private val now: ()->Long) {
    private var normal: ManagementScope?=null
    private var pending: ManagementEntry?=null
    private var issued=false
    fun bind(scope: ManagementScope) {
        if (scope==normal) return
        normal=scope; pending=null; issued=false
    }
    fun issue(scope: ManagementScope, expiresAt: Long): ManagementEntry? {
        if (scope!=normal || issued || now()>=expiresAt) return null
        issued=true
        return ManagementEntry(scope,expiresAt).also { pending=it }
    }
    /** Audio-owner final decision. Only a short in-memory transition belongs in decision. */
    fun accept(entry: ManagementEntry, epoch: Long, revision: Long, decision: ()->Boolean): Boolean {
        if (entry!==pending || entry.scope!=normal || entry.scope.epoch!=epoch || entry.scope.revision!=revision ||
            now()>=entry.expiresAt) return false
        pending=null; return decision()
    }
    fun clear() { normal=null; pending=null; issued=false }
}

/** A UI reservation is not a Grant. CAS prevents HOME/new-page races from reviving an old request. */
internal class ManagementPageRequests {
    enum class Phase { RESERVED, STOPPING }
    class Ticket internal constructor(val revision: Long, internal val phase: Phase)
    private val current=java.util.concurrent.atomic.AtomicReference<Ticket?>()
    fun reserve(revision: Long)=Ticket(revision,Phase.RESERVED).also(current::set)
    fun immediate(revision: Long) { current.set(Ticket(revision,Phase.STOPPING)) }
    fun claim(ticket: Ticket)=current.compareAndSet(ticket,Ticket(ticket.revision,Phase.STOPPING))
    fun requested(revision: Long)=current.get()?.let { it.revision==revision && it.phase==Phase.STOPPING }==true
    fun clear() { current.set(null) }
}
