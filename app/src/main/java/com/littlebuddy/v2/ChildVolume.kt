package com.littlebuddy.v2

/** Temporary child preference, never a write to the parent's durable settings. Audio owner only. */
internal class ChildVolume(cap: Int) {
    var limit=cap.coerceIn(0,100); private set
    var value=limit; private set
    private var scope: ManagementScope?=null
    private var consumed: String?=null
    fun bind(next: ManagementScope) { if(next!=scope) { scope=next;consumed=null } }
    fun clear() { scope=null;consumed=null }
    fun tighten(cap: Int) { limit=cap.coerceIn(0,100);value=value.coerceAtMost(limit) }
    fun accept(current: ManagementScope, token: String, direction: String): Int? {
        if(current!=scope || consumed!=null || !token.matches(Regex("[a-f0-9]{32}"))) return null
        val step=when(direction) { "up"->10;"down"->-10;else->return null }
        consumed=token;value=(value+step).coerceIn(0,limit);return value
    }
}
