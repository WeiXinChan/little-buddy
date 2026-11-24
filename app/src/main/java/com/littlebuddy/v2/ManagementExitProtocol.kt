package com.littlebuddy.v2

/** Local finite command protocol v2. Sample clock is absolute within one Capture.
 * No inference that silence means a new intention. No audio or transcript retained.
 */
internal class ManagementExitProtocol(private val now:()->Long=android.os.SystemClock::elapsedRealtime) {
 enum class State { CLEAR, UNCERTAIN, CONFIRM, EXITED }
 var state=State.CLEAR;private set
 private var generation=Long.MIN_VALUE
 private var requestEnd=-1L
 private var openedAt=-1L
 private var deadline=-1L
 private var wallDeadline=-1L
 private var nonce=0L
 private var requestedAt=-1L
 val confirmationNonce get()=nonce
 fun reset(value:Long){generation=value;state=State.CLEAR;requestEnd=-1;openedAt=-1;deadline=-1;nonce++}
 fun uncertain(){if(state!=State.EXITED){state=State.UNCERTAIN;openedAt=-1;deadline=-1;nonce++}}
 fun arm(value:Long,position:Long,ticket:Long):Boolean {
  if(state!=State.CONFIRM || value!=nonce || ticket!=generation || position<requestedAt || position>deadline || now()>wallDeadline)return false
  openedAt=position;return true
 }

 fun tick(position:Long){if(state==State.CONFIRM && (position>deadline || now()>wallDeadline))uncertain()}
 fun accept(name:String,start:Long,end:Long,position:Long,ticket:Long):String? {
  if(ticket!=generation)return null
  tick(position)
  if(end<=requestEnd || state==State.EXITED)return null
  requestEnd=end
  if(name=="继续管理" && state==State.CONFIRM && start<=openedAt)return null
  if(name=="继续管理") {state=State.CLEAR;openedAt=-1;deadline=-1;nonce++;return "继续管理"}
  if(name=="确认退出") {
   if(state==State.CONFIRM && start>openedAt && position<=deadline && now()<=wallDeadline){state=State.EXITED;nonce++;return "取消"}
   return null
  }
  if(name !in listOf("取消","退出管理"))return null
  when(state) {
   State.CLEAR -> {state=State.EXITED;return name}
   State.UNCERTAIN -> {state=State.CONFIRM;requestedAt=position;openedAt=Long.MAX_VALUE;deadline=position+128000;wallDeadline=now()+8000;nonce++;return "确认退出提示"}
   State.CONFIRM,State.EXITED -> return null
  }
 }
}
