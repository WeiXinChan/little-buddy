package com.littlebuddy.v2

/** Audio-handler owned. Leases prevent retired clients/routes from touching a newer native track. */
internal class OutputSlot {
    enum class Purpose { NORMAL, SERVICE_CUE }
    private var serial=0L
    private var current:Lease?=null
    var quarantined=false;private set
    val idle get()=current==null && !quarantined
    fun acquire(purpose:Purpose,factory:(()->Unit)->TrackPort,onRoute:()->Unit):TrackPort {
        check(idle)
        val ticket=++serial
        // Reservation exists before fallible construction (including synchronous route callbacks).
        val lease=Lease(ticket,purpose);current=lease
        try {lease.native=factory {if(current===lease && !lease.released)onRoute()};return lease}
        // A throwing factory has no typed native cleanup proof, even if it attempted release.
        catch(e:Throwable){quarantined=true;if(current===lease)current=null;throw e}
    }
    private inner class Lease(val ticket:Long,val purpose:Purpose):TrackPort {
        var native:TrackPort?=null
        var released=false
        private var stopped=false
        private var cleanupFailed=false
        private fun live():TrackPort {check(current===this && !released);return checkNotNull(native)}
        override val head get()=live().head
        override fun write(pcm:ShortArray,offset:Int)=live().write(pcm,offset)
        override fun setVolume(percent:Int)=live().setVolume(percent)
        override fun play()=live().play()
        private fun cleanup(block:(TrackPort)->Unit){
            if(released || current!==this)return
            try{block(live())}catch(e:Throwable){cleanupFailed=true;throw e}
        }
        override fun mute()=cleanup{it.mute()}
        override fun pause()=cleanup{it.pause()}
        override fun flush()=cleanup{it.flush()}
        override fun stop()=cleanup{it.stop();stopped=true}
        override fun release(){
            if(released || current!==this)return
            try{checkNotNull(native).release()}catch(e:Throwable){cleanupFailed=true;throw e}
            finally{
                released=true;native=null
                quarantined=quarantined || cleanupFailed || !stopped
                if(current===this)current=null
            }
        }
    }
}
