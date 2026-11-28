package com.littlebuddy.v2

/** No generic unlock. A typed grant is created only by current trusted SERVER_VOICE/single-response SERVER_TIMEOUT retirement. */
internal class RecoveryEpisode {
    class Ticket internal constructor(val episode:Long,val generation:Long)
    private var serial=0L
    private var generation=0L
    private var eligible=false
    private var promoted=false
    private var connecting=false
    private var cueUsed=false
    private var bound=false
    @Synchronized fun begin():Boolean {
        if(eligible)return false
        serial++;generation++;promoted=false;eligible=true;connecting=false;cueUsed=false;return true
    }
    @Synchronized fun grant(released:Boolean,permitted:Boolean):Ticket? {
        if(!eligible || connecting || !released || !permitted)return null
        bound=false;return Ticket(serial,++generation)
    }
    @Synchronized fun current(ticket:Ticket)= (eligible || promoted) && ticket.episode==serial && ticket.generation==generation
    @Synchronized fun consumeWake(ticket:Ticket):Boolean {
        if(!eligible || !current(ticket)||connecting)return false
        connecting=true;return true
    }
    @Synchronized fun cue(ticket:Ticket):Boolean {
        if(!eligible || !current(ticket)||cueUsed||connecting)return false
        cueUsed=true;return true
    }
    @Synchronized fun pause(){generation++;connecting=false;promoted=false}
    @Synchronized fun block(){generation++;eligible=false;connecting=false;promoted=false}
    @Synchronized fun hasEpisode()=eligible
    /** Emit one authenticated transport association; never a replacement CAPTURE_START. */
    @Synchronized fun binding(ticket:Ticket,physical:com.littlebuddy.v2.parent.PinDiagnostic.Scope,
        transport:Long,boundary:WakeBoundary):com.littlebuddy.v2.parent.PinDiagnostic.RuntimeEvent? {
        if(!current(ticket) || !connecting || bound || physical.activity<=0 || physical.capture<=0 ||
            transport<=physical.transport || boundary.boot<0 || boundary.tail<0 || boundary.observed<boundary.tail)return null
        bound=true
        return com.littlebuddy.v2.parent.PinDiagnostic.RuntimeEvent(
            com.littlebuddy.v2.parent.PinDiagnostic.RuntimeStage.RECOVERY_BIND,physical,
            currentTransport=transport,currentCapture=physical.capture,episode=ticket.episode,generation=ticket.generation,
            wakeBootMs=boundary.boot,wakeFrame=boundary.tail,readFrame=boundary.observed)
    }
    @Synchronized fun succeeded(ticket:Ticket):RecoveryWakeGrant? {
        if(!current(ticket)||!connecting)return null
        eligible=false;promoted=true;connecting=false;return RecoveryWakeGrant()
    }
    class RecoveryWakeGrant internal constructor()
}
