package com.littlebuddy.v2
/** Audio-owner only. Payload is never logged, copied to intents, or retried by time. */
internal class PendingConnection<T> {
 private var value:T?=null
 private var id=-1L
 private var generation=-1L
 fun offer(requestId:Long,ticket:Long,payload:T){id=requestId;generation=ticket;value=payload}
 fun invalidateThrough(cancelledId:Long){if(id<=cancelledId)invalidate()}
 fun invalidate(){value=null;id=-1;generation=-1}
 val present get()=value!=null
 fun take(requestId:Long,eligible:(Long)->Boolean,releasedWorkerAndLease:Boolean):T? {
  if(value==null)return null
  if(id!=requestId || !eligible(generation)){invalidate();return null}
  if(!releasedWorkerAndLease)return null
  val result=value;invalidate();return result
 }
}
