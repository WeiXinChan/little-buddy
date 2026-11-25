package com.littlebuddy.v2

/** Process-wide, shared by child and local management. Native release alone is NOT worker exit.
 * A stuck constructor/JNI/destructor or failed release keeps the process fail-closed. */
internal object ProcessRecorders {
    private var current: RecorderLease?=null
    @Synchronized fun acquire(kind:String):RecorderLease? {
        if(current!=null)return null
        return RecorderLease(kind).also{current=it}
    }
    @Synchronized internal fun complete(lease:RecorderLease) {
        if(current===lease && lease.complete())current=null
    }
    @Synchronized fun diagnostic()=current?.diagnostic() ?: "released"
}
internal class RecorderLease internal constructor(private val kind:String) {
    private var native=false
    private var worker=false
    private var models=false
    private var stops=0
    fun nativeReleased() {synchronized(this){native=true};ProcessRecorders.complete(this)}
    fun modelsReleased(){synchronized(this){models=true};ProcessRecorders.complete(this)}
    fun workerFinished() {synchronized(this){worker=true};ProcessRecorders.complete(this)}
    @Synchronized fun beginStop():Boolean {if(native)return false;stops++;return true}
    fun endStop() {synchronized(this){stops--};ProcessRecorders.complete(this)}
    @Synchronized internal fun complete()=native && models && worker && stops==0
    @Synchronized fun diagnostic()="$kind:native_released=$native,worker_finished=$worker,models_released=$models,stop_tasks=$stops"
}
