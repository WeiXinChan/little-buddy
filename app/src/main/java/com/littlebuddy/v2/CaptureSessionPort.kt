package com.littlebuddy.v2

/** Capture owns hardware and coordinates; a port owns only the current consumer.
 * stage takes ownership (including rejection) iff it returns true. */
internal data class WakeBoundary(val boot:Long,val tail:Long,val observed:Long,val relativeMs:Long)
internal interface CaptureSessionPort {
    val idleSerial:Long
    val inputSerial:Long
    fun stageWake(boundary:WakeBoundary) {}
    fun wake(boundary:WakeBoundary)
    fun frame(pcm:ShortArray,speech:Boolean,capturedAt:Long)
    fun quiet()
    fun stage(batch:List<ShortArray>,speech:Boolean,capturedAt:Long):Boolean=false
    fun speechBeforeWake() {}
    fun check() {}
    fun cancel() {}
}
internal class ClientCapturePort(private val client:VoiceClient):CaptureSessionPort {
    override val idleSerial get()=client.idleSerial
    override val inputSerial get()=client.inputSerial
    override fun wake(boundary:WakeBoundary){client.wake(boundary.boot,boundary.tail,boundary.observed,boundary.relativeMs)}
    override fun frame(pcm:ShortArray,speech:Boolean,capturedAt:Long)=client.frame(pcm,speech,capturedAt)
    override fun quiet()=client.quiet()
}
