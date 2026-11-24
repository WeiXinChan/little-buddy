package com.littlebuddy.v2
/** Native capture position, never a read-completion wall time. Unknown stays unarmed. */
internal object CaptureFreshness {
 fun marker(promptNano:Long,framePosition:Long,timestampNano:Long,readFrames:Long,nowNano:Long):Long? {
  if(promptNano<=0 || timestampNano<promptNano || timestampNano>nowNano || framePosition<readFrames || framePosition<0)return null
  return framePosition
 }
}
