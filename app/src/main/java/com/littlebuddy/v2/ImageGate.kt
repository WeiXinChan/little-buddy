package com.littlebuddy.v2

internal data class ImageScope(val session: String, val turn: Long, val epoch: Long, val revision: Long)
internal data class ImageAsset(val id: String, val sha256: String, val width: Int, val height: Int)
internal data class ImageReady(val scope: ImageScope, val topic: Int, val token: String, val asset: ImageAsset,
                              val imageId: String = token, val source: String = "default")
internal data class ImageReveal(val ready: ImageReady, val player: String, val stream: Int, val segment: String, val end: Long)
internal interface ImagePort {
    fun bind(scope: ImageScope)
    fun ready(value: ImageReady)
    fun reveal(value: ImageReveal)
    fun acknowledged(player: String, stream: Int, segment: String, end: Long)
    fun clear()
    fun inputChanged() = clear()
    fun outputRevoked() = clear()
    fun expired(value: ImageReady, retainMs: Long) { clear() }
    fun begin(value: ImageReady, bytes: Int, chunks: Int, chunkBytes: Int, retainMs: Long) { clear() }
    fun chunk(value: ImageReady, index: Int, offset: Int, data: ByteArray) { data.fill(0);clear() }
    fun readyV2(value: ImageReady, retainMs: Long) = ready(value)
    fun display(value: ImageReveal, action: String, durationMs: Long, retainMs: Long) { clear() }
}

/** One decoded slot, exact ACK and a non-renewable material deadline. No IO under this monitor. */
internal class ImageGate<T>(private val now: ()->Long = { 0L }, private val dispose: (T)->Unit = {},
                           private val changed: () -> Unit) {
    private var scope: ImageScope?=null
    private var session: String?=null
    private var serial=0L
    private var prepared: ImageReady?=null
    private var loaded: T?=null
    private var used=false
    private var publicCache=false
    private var visible=false
    private var displayEnd=0L
    private var retainEnd=0L
    private val deadlines=LinkedHashMap<String,Long>()
    private val acks=LinkedHashSet<List<Any>>()
    private val tokens=HashSet<String>()
    private fun releaseLoaded() { val old=loaded;loaded=null;changed();old?.let(dispose) }
    @Synchronized fun bind(value: ImageScope) {
        if(value==scope)return
        if(session!=value.session) clear()
        else inputChanged()
        session=value.session;scope=value
    }
    @Synchronized fun clear() {
        serial++;scope=null;session=null;prepared=null;visible=false;publicCache=false;used=false
        acks.clear();tokens.clear();deadlines.clear();releaseLoaded()
    }
    /** Revoke native output and pixels; retain only non-authorizing ID deadline tombstones. */
    @Synchronized fun outputRevoked() {
        serial++;scope=null;prepared=null;visible=false;publicCache=false;used=false
        acks.clear();tokens.clear();releaseLoaded()
    }
    @Synchronized fun inputChanged() {
        serial++;scope=null;visible=false;used=false;acks.clear();tokens.clear()
        if(!publicCache || loaded==null || now()>=retainEnd) { prepared=null;publicCache=false;releaseLoaded() }
        else changed()
    }
    @Synchronized fun expired(value: ImageReady, retainMs: Long) {
        if(value!=prepared || value.scope!=scope)return
        visible=false
        if(retainMs<=0) { retainEnd=now();tick() } else { retainEnd=minOf(retainEnd,now()+retainMs);changed() }
    }
    @Synchronized fun tick() {
        if(prepared!=null && now()>=retainEnd) {
            serial++;prepared=null;visible=false;publicCache=false;used=true;releaseLoaded()
        } else if(visible && now()>=displayEnd) { visible=false;changed() }
    }
    /** Preparation topic is future committed topic, not the old rendered topic. */
    @Synchronized fun prepare(value: ImageReady, retainMs: Long=15000): Long? {
        tick()
        if(value.scope!=scope || value.topic<0 || retainMs !in 1..15000 ||
            !value.token.matches(Regex("[a-f0-9]{32}")) || !value.imageId.matches(Regex("[a-f0-9]{32}")))return null
        if(tokens.size>=256 || !tokens.add(value.token))return null
        val end=minOf(deadlines[value.imageId] ?: (now()+retainMs),now()+retainMs)
        if(now()>=end || (deadlines.size>=256 && value.imageId !in deadlines))return null
        deadlines[value.imageId]=end
        val reuse=publicCache && loaded!=null && prepared?.imageId==value.imageId && prepared?.asset==value.asset &&
            prepared?.source==value.source && prepared?.scope?.session==value.scope.session && (value.topic==prepared?.topic || value.topic.toLong()==(prepared?.topic?.toLong() ?: -2)+1)
        serial++;visible=false;used=false;retainEnd=end
        if(!reuse) { publicCache=false;releaseLoaded() }
        prepared=value;changed();return serial
    }
    @Synchronized fun isCurrent(ticket: Long) : Boolean { tick();return serial==ticket && prepared?.scope==scope && now()<retainEnd }
    @Synchronized fun loaded(ticket: Long, value: T) {
        if(!isCurrent(ticket)) { dispose(value);return }
        if(loaded!==value)releaseLoaded()
        loaded=value;if(visible)changed()
    }
    @Synchronized fun failed(ticket: Long) {
        if(ticket!=serial)return
        serial++;prepared=null;visible=false;publicCache=false;used=true;releaseLoaded()
    }
    @Synchronized fun acknowledged(player: String, stream: Int, segment: String, end: Long) {
        if(scope==null)return
        if(acks.size==128)acks.remove(acks.first())
        acks.add(listOf(player,stream,segment,end))
    }
    @Synchronized fun reveal(value: ImageReveal): Boolean = display(value,"display",6000,15000)
    @Synchronized fun display(value: ImageReveal, action: String, durationMs: Long, retainMs: Long): Boolean {
        tick()
        if(value.ready.scope!=scope || retainMs !in 1..15000 ||
            listOf(value.player,value.stream,value.segment,value.end) !in acks)return false
        if(prepared!=value.ready) {
            if(!publicCache || loaded==null || prepared?.imageId!=value.ready.imageId || prepared?.asset!=value.ready.asset ||
                prepared?.source!=value.ready.source || (value.ready.topic!=prepared?.topic && value.ready.topic.toLong()!=(prepared?.topic?.toLong() ?: -2)+1) ||
                prepared?.scope?.session!=value.ready.scope.session || prepare(value.ready,retainMs)==null)return false
        }
        if(used || action !in setOf("display","extend","reshow","hide") ||
            (if(action=="hide")durationMs!=0L else if(action=="extend")durationMs !in 1..15000 else durationMs !in 1..12000))return false
        retainEnd=minOf(retainEnd,now()+retainMs);deadlines[value.ready.imageId]=retainEnd
        if(now()>=retainEnd)return false
        used=true;publicCache=true
        displayEnd=when(action) { "hide"->now();"extend"->minOf(retainEnd,now()+durationMs)
            else->minOf(retainEnd,now()+durationMs) }
        visible=action!="hide";changed();return true
    }
    @Synchronized fun render(draw: (T?) -> Unit) { tick();draw(if(visible && prepared?.scope==scope)loaded else null) }
}
