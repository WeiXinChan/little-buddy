package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
class Review97Test {
 private class Native : TrackPort {
  var pos=0L; var released=false
  override val head get()=pos
  override fun write(pcm: ShortArray, offset:Int)=pcm.size-offset
  override fun play() {}
  override fun pause() {}
  override fun mute() {}
  override fun flush() {}
  override fun stop() {}
  override fun release() {released=true}
 }
 @Test fun lateHeadMustNotRenewExpiredPlayback() {
  var time=0L; val n=Native(); val acks=mutableListOf<PlaybackAck>()
  val p=Playback({n},{time},acks::add); val b=Binding(1,"review",1)
  p.bind(b); p.enqueue(AudioPacket(b,"a",0,100,ShortArray(100){1})); p.tick()
  time=60000; n.pos=50
  try {p.tick()} catch (_:IllegalStateException) {}
  assertTrue("expired native player must be released before processing late head",n.released)
  assertNull(p.binding)
 }
 @Test fun validProgressBeforeDeadlineStillRenews() {
  var time=0L; val n=Native(); val p=Playback({n},{time},{})
  val b=Binding(1,"review",1); p.bind(b); p.enqueue(AudioPacket(b,"a",0,100,ShortArray(100){1})); p.tick()
  time=59999; n.pos=50; p.tick(); time=60000; p.tick(); assertEquals(b,p.binding)
  p.stop()
 }
}
