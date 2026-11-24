package com.littlebuddy.v2

/** Local management output only; no VoiceClient, context, network or credentials. */
internal class ManagedPromptPlayback(factory:()->TrackPort,private val now:()->Long,private val audible:()->Boolean) {
 private val output=Playback(factory,now,{})
 private var pcm=ShortArray(0)
 private var queued=0
 private var startedAt=0L
 var result:Boolean?=null;private set
 val proof get()=output.nativeProof()
 val quarantined get()=output.quarantined
 fun begin(data:ShortArray){
  require(data.isNotEmpty() && data.size<=120000)
  pcm=data;startedAt=now()
  try{check(audible());output.bind(Binding(0,"local-management",0))}catch(_:Exception){finish(false)}
 }
 fun tick(){
  if(result!=null)return
  try {
   check(audible() && now()-startedAt<=6000)
   while(queued<pcm.size && queued-output.nativeProof().observedHead<12000){
    val end=minOf(queued+2400,pcm.size)
    check(output.enqueue(AudioPacket(checkNotNull(output.binding),"local-management",queued.toLong(),end.toLong(),pcm.copyOfRange(queued,end))))
    queued=end
   }
   output.tick()
   if(queued==pcm.size && !output.hasPending && output.nativeProof().observedHead>=pcm.size)finish(true)
  }catch(_:Exception){finish(false)}
 }
 private fun finish(success:Boolean){val stopped=output.stop();pcm.fill(0);pcm=ShortArray(0);result=success && stopped==StopResult(true,true)}
 fun cancel(){if(result==null)finish(false)}
}
