package com.littlebuddy.v2

/** One real wake, one connect, one FIFO. No network/captured speech retention before wake.
 * Worker calls stage/check; owner calls wake/ready/drain. No lock is held across consumer/JNI. */
internal class RecoveryHandoff(private val now:()->Long,private val post:(Runnable)->Boolean,
    private val allowed:()->Boolean,private val connect:(WakeBoundary)->Unit,
    private val cancelCue:()->Unit,private val failed:()->Unit,private val imported:()->Unit):CaptureSessionPort {
    private data class Item(val pcm:ShortArray?,val speech:Boolean,val at:Long)
    enum class State { LOCAL, CONNECTING, IMPORTING, LIVE, CANCELLED }
    enum class Rejection { PERMISSION, CLOCK_ORDER, CONNECT_DEADLINE, PCM_AGE, CONSUMER }
    @Volatile var rejection:Rejection?=null;private set
    @Volatile var rejectedAtBoot=-1L;private set
    @Volatile var state=State.LOCAL;private set
    private var boundary:WakeBoundary?=null
    private var client:VoiceClient?=null
    private val queue=ArrayDeque<Item>()
    private var samples=0
    private var scheduled=false
    private var inFlight:Item?=null
    private var failurePosted=false
    private var wakeDispatched=false
    private val cueRevoked=java.util.concurrent.atomic.AtomicBoolean(false)
    val cuePermitted get()=!cueRevoked.get()
    override val idleSerial get()=if(state==State.LIVE)client?.idleSerial ?: 0 else 0
    override val inputSerial get()=if(state==State.LIVE)client?.inputSerial ?: 0 else 0
    private fun violationLocked():Rejection? {
        if(!allowed())return Rejection.PERMISSION
        val t=now();val b=boundary
        if(b!=null && t<b.boot)return Rejection.CLOCK_ORDER
        if(b!=null && state==State.CONNECTING && t>=b.boot+2500)return Rejection.CONNECT_DEADLINE
        if(queue.any{it.pcm!=null && t-it.at !in 0 until 3000} ||
            inFlight?.let{t-it.at !in 0 until 3000}==true)return Rejection.PCM_AGE
        return null
    }
    private fun validLocked()=state!=State.CANCELLED && violationLocked()==null
    private fun clearLocked(){queue.forEach{it.pcm?.fill(0)};queue.clear();inFlight?.pcm?.fill(0);samples=inFlight?.pcm?.size ?: 0;state=State.CANCELLED;client=null}
    private fun reject(){
        val report=synchronized(this){
            if(state==State.CANCELLED)false else {
                rejection=violationLocked() ?: Rejection.CONSUMER;rejectedAtBoot=now()
                clearLocked();if(failurePosted)false else{failurePosted=true;true}
            }
        }
        if(report)post(Runnable{failed()})
    }
    /** Both the client pump and capture worker can observe expiry first. Record/zero once,
     * before returning false; a later lifecycle close cannot erase the budget evidence. */
    internal fun admitted():Boolean {
        if(synchronized(this){validLocked()})return true
        reject();return false
    }
    override fun cancel(){synchronized(this){clearLocked()}}
    override fun check(){if(!synchronized(this){validLocked()}){reject();error("recovery handoff rejected")}}
    override fun speechBeforeWake(){if(cueRevoked.compareAndSet(false,true))post(Runnable{if(allowed() && state!=State.CANCELLED)cancelCue()})}
    override fun stageWake(boundary:WakeBoundary){
        val accepted=synchronized(this){
            if(state!=State.LOCAL || !validLocked())false else {
                this.boundary=boundary;state=State.CONNECTING;true
            }
        }
        if(!accepted)check()
    }
    override fun wake(boundary:WakeBoundary){
        val accepted=synchronized(this){if(state!=State.CONNECTING || wakeDispatched || this.boundary!=boundary)false else{wakeDispatched=true;true}}
        if(accepted){cueRevoked.set(true);if(synchronized(this){validLocked()}){cancelCue();connect(boundary)}else reject()}
    }
    override fun stage(batch:List<ShortArray>,speech:Boolean,capturedAt:Long):Boolean {
        var reject=false
        synchronized(this){
            if(state==State.LIVE)return false
            val count=batch.sumOf{it.size.toLong()}
            if(state !in setOf(State.CONNECTING,State.IMPORTING) || !validLocked() ||
                count>48000-samples || queue.size+batch.size>512 || batch.any{it.isEmpty() || it.size>320}) {
                batch.forEach{it.fill(0)};reject=true
            } else {
                var remaining=count
                batch.forEach { pcm ->
                    val at=capturedAt-NativeReadLedger.durationMs(remaining)
                    queue.addLast(Item(pcm,speech,at));samples+=pcm.size;remaining-=pcm.size
                }
                if(!validLocked())reject=true
            }
        }
        if(reject)reject() else schedule()
        return true
    }
    override fun frame(pcm:ShortArray,speech:Boolean,capturedAt:Long){
        val target=synchronized(this){if(state==State.LIVE && allowed())client else null}
        if(target!=null)target.frame(pcm,speech,capturedAt) else pcm.fill(0)
    }
    override fun quiet(){
        val target=synchronized(this){
            if(state==State.LIVE)client else {
                if(state in setOf(State.CONNECTING,State.IMPORTING) && queue.lastOrNull()?.pcm!=null && queue.size<512)
                    queue.addLast(Item(null,false,now()))
                null
            }
        }
        target?.quiet()
    }
    /** Owner only; gate ticks are inhibited before wake and until the queue becomes empty. */
    fun ready(value:VoiceClient):Boolean {
        synchronized(this){
            if(state!=State.CONNECTING)return state in setOf(State.IMPORTING,State.LIVE) && client===value
        }
        val b=synchronized(this){
            if(state!=State.CONNECTING || !validLocked())null else {
                state=State.IMPORTING;client=value;boundary
            }
        } ?: run{reject();return false}
        value.beginCaptureImport(b.boot)
        value.wake(b.boot,b.tail,b.observed,b.relativeMs)
        schedule();return true
    }
    private fun schedule(){
        val start=synchronized(this){if(state==State.IMPORTING && !scheduled){scheduled=true;true}else false}
        if(start && !post(Runnable{drain()}))reject()
    }
    private fun drain(){
        repeat(4){
            var complete=false
            val pair=synchronized(this){
                if(state!=State.IMPORTING)return
                if(!validLocked()){null}else if(queue.isEmpty()){
                    state=State.LIVE;scheduled=false;complete=true;client?.let{it to null}
                }else{val item=queue.removeFirst();inFlight=item;client?.let{it to item}}
            }
            if(pair==null){reject();return}
            val (target,item)=pair
            if(complete){
                try{check(allowed());target.endCaptureImport();imported()}catch(_:Exception){reject()}
                return
            }
            try {
                check(allowed())
                checkNotNull(item)
                if(item.pcm==null)target.quiet() else target.frame(item.pcm,item.speech,item.at)
            }catch(_:Exception){reject();return}
            finally{synchronized(this){if(item?.pcm!=null)samples-=item.pcm.size;item?.pcm?.fill(0);inFlight=null}}
        }
        synchronized(this){scheduled=false}
        schedule()
    }
    internal fun retainedSamples()=synchronized(this){samples}
}
