package com.littlebuddy.v2
/** No continuity promise beyond observed native room; reserve one read and cap at100ms. */
internal object NativeRetention {
 fun budgetMs(bufferFrames:Long,unreadFrames:Long?,timestampAgeMs:Long):Long {
  if(unreadFrames==null || timestampAgeMs !in 0..40)return 0
  return (((bufferFrames-unreadFrames.coerceAtLeast(0)-timestampAgeMs*16-320).coerceAtLeast(0)*1000)/16000).coerceAtMost(100)
 }
}
internal class InputContinuityInterrupted:IllegalStateException()
