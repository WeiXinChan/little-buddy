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
}
