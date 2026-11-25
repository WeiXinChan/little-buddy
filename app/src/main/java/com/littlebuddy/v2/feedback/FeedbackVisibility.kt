package com.littlebuddy.v2.feedback

/** Parent content projection has its own deadline check, including a UI job delayed past expiry. */
internal class FeedbackVisibility(private val clock: FeedbackClock) {
    fun now()=clock.now()
    private fun material(item:FeedbackView)=item.description!=null || item.reply!=null || item.logs.count>0
    fun until(screen:FeedbackScreen):Long? = when(screen) {
        is FeedbackScreen.Detail -> screen.item.deleteBy.takeIf{material(screen.item)}
        is FeedbackScreen.Preview -> screen.logs.from?.let{it+WEEK}
        is FeedbackScreen.Issues -> screen.items.filter(::material).minOfOrNull{it.deleteBy}
        else->null
    }
    fun allowed(screen:FeedbackScreen):Boolean {
        val end=until(screen) ?: return true
        val time=clock.now() ?: return false
        return time>=0 && time<end
    }
}

/** UI-thread transaction: build after scrub, then arm. Nested render/cancel owns a new generation. */
internal class FeedbackProjection(private val now:()->Long?,
    private val post:(Runnable,Long)->Unit,private val remove:(Runnable)->Unit,
    private val valid:()->Boolean,private val revoked:()->Unit,private val expired:()->Unit) {
    private var generation=0L
    private var task:Runnable?=null
    fun clearTimer() { task?.let(remove);task=null }
    fun cancel() { generation++;clearTimer() }
    fun render(deadline:Long?,build:()->Unit) {
        cancel();val ticket=generation
        build()
        if(ticket!=generation || deadline==null)return
        val check=object:Runnable {
            override fun run() {
                if(ticket!=generation)return
                task=null
                if(!valid()) { cancel();revoked();return }
                val time=now()
                if(time==null || time<0 || time>=deadline) { cancel();expired();return }
                task=this;post(this,minOf(500L,deadline-time))
            }
        }
        task=check;post(check,1L)
    }
}
