package com.littlebuddy.v2.feedback
import org.junit.Assert.*
import org.junit.Test
class FeedbackVisibilityTest {
    private fun item(description:String?="synthetic",reply:String?="reply",until:Long=2000)=FeedbackView("id",Category.OTHER,description,FeedbackState.REPLIED,1000,until,reply)
    @Test fun delayedParentDetailCannotRenderAtOrAfterMaterialDeadline() {
        var now=1999L;val gate=FeedbackVisibility{now};val screen=FeedbackScreen.Detail(item())
        assertTrue(gate.allowed(screen));now=2000;assertFalse(gate.allowed(screen));now++;assertFalse(gate.allowed(screen))
    }
    @Test fun previewCannotReshowExpiredSelectedLogSnapshot() {
        var now=1000L+WEEK-1;val gate=FeedbackVisibility{now}
        val screen=FeedbackScreen.Preview(Category.OTHER,"synthetic",LogPreview(1000,1001,1,20),true)
        assertTrue(gate.allowed(screen));now++;assertFalse(gate.allowed(screen))
    }
    @Test fun deletionMetadataIsNotConfusedWithRetainedMaterial() {
        val gate=FeedbackVisibility{9000L}
        assertTrue(gate.allowed(FeedbackScreen.Detail(item(null,null))))
        assertTrue(gate.allowed(FeedbackScreen.Issues(listOf(item(null,null)),true)))
        assertFalse(gate.allowed(FeedbackScreen.Issues(listOf(item()),true)))
    }
    @Test fun untrustedClockNeverPublishesMaterialButCanShowHonestNotice() {
        for(clock in listOf(FeedbackClock{null},FeedbackClock{-1})) {
            val gate=FeedbackVisibility(clock)
            assertFalse(gate.allowed(FeedbackScreen.Detail(item())))
            assertTrue(gate.allowed(FeedbackScreen.Notice(Failure.CLOCK)))
        }
    }

    private class Rig {
        var time=1000L;var text="";var valid=true
        val queued=mutableListOf<Runnable>()
        lateinit var projection:FeedbackProjection
        init { projection=FeedbackProjection({time},{r,_->queued.add(r)},{r->queued.remove(r)},
            {valid},{text="locked"},{text=""}) }
        fun render(until:Long?,body:()->Unit={text="private"})=projection.render(until) {
            projection.clearTimer();text="";body()
        }
    }
    @Test fun scrubBuildArmThenControlledExpiryClearsVisibleText() {
        val r=Rig();r.render(2000);assertEquals("private",r.text)
        assertEquals(1,r.queued.size);r.time=2000;r.queued.removeAt(0).run()
        assertEquals("",r.text);assertTrue(r.queued.isEmpty())
    }
    @Test fun homeCloseAndDequeuedOldCallbackCannotClearNewPage() {
        val r=Rig();r.render(2000);val old=r.queued.single()
        r.projection.cancel();r.text="";assertTrue(r.queued.isEmpty())
        r.render(4000){r.text="new"};r.time=2500;old.run()
        assertEquals("new",r.text);assertEquals(1,r.queued.size)
        r.projection.cancel();assertTrue(r.queued.isEmpty())
    }
    @Test fun nestedRenderOrCloseNeverRearmsOuterTimer() {
        val r=Rig();r.render(2000){r.render(null){r.text="notice"}}
        assertEquals("notice",r.text);assertTrue(r.queued.isEmpty())
        r.render(2000){r.projection.cancel();r.text="closed"}
        assertEquals("closed",r.text);assertTrue(r.queued.isEmpty())
        r.render(2000);r.render(null){r.text="locked"};assertTrue(r.queued.isEmpty())
    }
    @Test fun revokedVisibleProjectionLocksWithoutBorrowingAuthority() {
        val r=Rig();r.render(2000);r.valid=false;r.queued.removeAt(0).run()
        assertEquals("locked",r.text);assertTrue(r.queued.isEmpty())
    }
}
