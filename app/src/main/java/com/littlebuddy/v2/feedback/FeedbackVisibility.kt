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
