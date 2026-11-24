package com.littlebuddy.v2

/** v2.1: bounded prompt preparation, then exactly one fixed audible-completion window. */
internal class ManagementExitProtocol(private val now:()->Long=android.os.SystemClock::elapsedRealtime) {
 enum class State { CLEAR, UNCERTAIN, PREPARING, CONFIRM, EXITED }
 var state=State.CLEAR;private set
 private var generation=Long.MIN_VALUE
 private var requestEnd=-1L
 private var openedAt=-1L
 private var nonce=0L
 private var requestedAt=-1L
 private var preparationIssued=-1L
 private var preparationDeadline=-1L
 private var wallDeadline=-1L
 val confirmationNonce get()=nonce
 fun reset(value:Long){generation=value;state=State.CLEAR;requestEnd=-1;openedAt=-1;wallDeadline=-1;nonce++}
 fun uncertain(){if(state!=State.EXITED){state=State.UNCERTAIN;openedAt=-1;wallDeadline=-1;nonce++}}
 fun promptComplete(value:Long,ticket:Long,completedAtMs:Long):Boolean {
  if(state!=State.PREPARING || value!=nonce || ticket!=generation || completedAtMs<preparationIssued || completedAtMs>preparationDeadline || completedAtMs>now() || now()>completedAtMs+8000){return false}
  state=State.CONFIRM;wallDeadline=completedAtMs+8000;return true
 }
 fun arm(value:Long,position:Long,ticket:Long):Boolean {
  if(state!=State.CONFIRM || value!=nonce || ticket!=generation || position<requestedAt || now()>wallDeadline)return false
  openedAt=position;return true
 }
 fun tick(position:Long){if((state==State.PREPARING && now()>preparationDeadline) || (state==State.CONFIRM && now()>wallDeadline))uncertain()}
 fun accept(name:String,start:Long,end:Long,position:Long,ticket:Long):String? {
  if(ticket!=generation)return null
  tick(position)
  if(end<=requestEnd || state==State.EXITED)return null
  requestEnd=end
  if(name=="继续管理" && state in listOf(State.PREPARING,State.CONFIRM) && start<=openedAt)return null
  if(name=="继续管理") {state=State.CLEAR;openedAt=-1;wallDeadline=-1;nonce++;return "继续管理"}
  if(name=="确认退出") {
   if(state==State.CONFIRM && start>openedAt && now()<=wallDeadline){state=State.EXITED;nonce++;return "取消"}
   return null
  }
  if(name !in listOf("取消","退出管理"))return null
  when(state) {
   State.CLEAR -> {state=State.EXITED;return name}
   State.UNCERTAIN -> {state=State.PREPARING;requestedAt=position;openedAt=Long.MAX_VALUE;preparationIssued=now();preparationDeadline=now()+6000;nonce++;return "确认退出提示"}
   State.PREPARING,State.CONFIRM,State.EXITED -> return null
  }
 }
}
