package com.littlebuddy.v2
/** Owner-thread subscription identity; queued signals cannot consume a replacement. */
internal class OwnerLeaseWait {
 private class Wait(val request:Long,val generation:Long,var cancel:(()->Unit)?=null)
 private var current:Wait?=null
 fun begin(request:Long,generation:Long,subscribe:((()->Unit)->(()->Unit)),ready:()->Unit){
  if(current?.let{it.request==request && it.generation==generation}==true)return
  cancelAll();val wait=Wait(request,generation);current=wait
  val cancel=subscribe{if(current===wait){current=null;ready()}}
  if(current===wait)wait.cancel=cancel else cancel()
 }
 fun cancelAll(){val old=current;current=null;old?.cancel?.invoke()}
 fun cancelThrough(request:Long,generation:Long){val old=current?:return;if(old.request<request || old.request==request && old.generation<=generation)cancelAll()}
}
