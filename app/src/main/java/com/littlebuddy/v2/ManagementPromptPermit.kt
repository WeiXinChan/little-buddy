package com.littlebuddy.v2
/** Cross-thread preparation grant; never a renewable confirmation window. */
internal class ManagementPromptPermit(private val now:()->Long) {
 private data class Grant(val nonce:Long,val generation:Long,val until:Long)
 @Volatile private var current:Grant?=null
 fun offer(nonce:Long,generation:Long){current=Grant(nonce,generation,now()+6000)}
 fun valid(nonce:Long,generation:Long):Boolean {val g=current;return g!=null && g.nonce==nonce && g.generation==generation && now()<=g.until}
 fun revoke(nonce:Long,generation:Long){if(current?.let{it.nonce==nonce && it.generation==generation}==true)current=null}
}
