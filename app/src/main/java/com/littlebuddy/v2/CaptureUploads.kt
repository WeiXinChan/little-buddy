package com.littlebuddy.v2

/** Single recorder producer, audio-owner consumer. One scheduled drain, bounded samples.
 * Pending capacity equals the existing wake ring; a waiting producer retains at most
 * one additional ring-sized batch. Cancellation discards only invalidated ownership.
 */
internal class CaptureUploads(
 private val post: (()->Unit)->Boolean,
 private val eligible:(Long)->Boolean,
 private val deliver:(ShortArray,Boolean,Long)->Unit,
 private val failed:(Exception)->Unit,
 private val waiting:()->Unit={},
 private val capacity:Int=16000,
 private val now:()->Long={System.nanoTime()/1_000_000}
) {
 private data class Batch(val frames:List<ShortArray>,val speech:Boolean,val ticket:Long,val time:Long){val samples=frames.sumOf{it.size}}
 private val lock=Object()
 private val queue=ArrayDeque<Batch>()
 private var held=0
 private var scheduled=false
 private var closed=false
 val heldSamples get()=synchronized(lock){held}
 private fun wipe(batch:Batch){batch.frames.forEach{it.fill(0)}}
 fun submit(frames:List<ShortArray>,speech:Boolean,ticket:Long,time:Long,retentionBudget:()->Long={100L}):Boolean {
  if(frames.isEmpty())return true
  val batch=Batch(frames,speech,ticket,time)
  require(batch.samples<=capacity && frames.all{it.size<=320})
  var start=false
  synchronized(lock){
   var deadline:Long?=null
   var notified=false
   while(!closed && eligible(ticket) && held+batch.samples>capacity){
    if(deadline==null)deadline=now()+retentionBudget().coerceIn(0,100)
    if(closed || !eligible(ticket)){wipe(batch);return false}
    val left=deadline-now()
    if(left<=0){wipe(batch);close();throw InputContinuityInterrupted()}
    if(!notified){waiting();notified=true}
    try{lock.wait(left)}catch(e:InterruptedException){wipe(batch);throw e}
   }
   if(closed || !eligible(ticket)){wipe(batch);return false}
   held+=batch.samples;queue.addLast(batch)
   if(!scheduled){scheduled=true;start=true}
  }
  if(start && !post{drain()}){close();error("capture owner unavailable")}
  return true
 }
 private fun drain(){
  val batch=synchronized(lock){if(queue.isEmpty()){scheduled=false;null}else queue.removeFirst()}?:return
  try {
   for(frame in batch.frames){
    if(!synchronized(lock){closed} && eligible(batch.ticket))deliver(frame,batch.speech,batch.time)
    frame.fill(0)
   }
  }catch(e:Exception){close();failed(e)}
  finally {
   wipe(batch)
   val next=synchronized(lock){held-=batch.samples;lock.notifyAll();if(queue.isEmpty()){scheduled=false;false}else true}
   if(next && !post{drain()}){close();failed(IllegalStateException("capture owner unavailable"))}
  }
 }
 fun invalidate(){synchronized(lock){while(queue.isNotEmpty()){val b=queue.removeFirst();held-=b.samples;wipe(b)};lock.notifyAll()}}
 fun close(){synchronized(lock){closed=true;invalidate()}}
}
