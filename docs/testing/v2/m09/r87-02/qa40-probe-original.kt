package com.littlebuddy.v2.feedback

import java.nio.file.Files
import javax.crypto.KeyGenerator
import org.junit.Assert.*
import org.junit.Test

class Review40Probe {
    private class Queue : FeedbackQueue {
        private val jobs = ArrayDeque<() -> Unit>()
        override fun post(action: () -> Unit) { jobs.addLast(action) }
        fun drain() { while(jobs.isNotEmpty()) jobs.removeFirst()() }
    }
    private class Clock(var time: Long = 1000L) : FeedbackClock { override fun now()=time }
    private class Auth : FeedbackPageAuthority {
        private class Intent(val epoch: Int) : ParentIntent
        private var epoch=0; private var alive=true
        override fun current()=alive
        override fun invalidate() {epoch++}
        override fun close() {alive=false;epoch++}
        override fun prepare(operation: Operation,digest: String): ParentIntent? = if(alive) Intent(epoch) else null
        override fun accept(intent: ParentIntent,operation: Operation,digest: String,acceptance: ()->Unit): Boolean {
            if(!alive || (intent as Intent).epoch!=epoch) return false
            acceptance();return true
        }
    }
    @Test fun systemSweepMustRetireDisplayedExpiredDetails() {
        val dir=Files.createTempDirectory("qa40-detail-expiry-").toFile()
        try {
            val key=KeyGenerator.getInstance("AES").apply{init(256)}.generateKey()
            val clock=Clock();val work=Queue();val ui=Queue();val screens=mutableListOf<FeedbackScreen>()
            lateinit var core:FeedbackCore
            val provider=object:FeedbackProvider {
                override fun available()=true
                override fun submit(idempotencyKey:String,payload:FeedbackPayload,admit:()->Boolean):SubmitReceipt {
                    check(admit());return SubmitReceipt(clock.time)
                }
                override fun withdraw(idempotencyKey:String)=DeleteReceipt(clock.time,true)
            }
            val engine=FeedbackEngine(work,ui,{auth -> FeedbackCore(FeedbackVault(PrivateVaultFiles(dir),key),clock,auth,provider).also{core=it}},{true})
            fun drain(){work.drain();ui.drain()}
            val old=engine.open(Auth(),screens::add);drain()
            old.preview(Category.OTHER,"QA40_SYNTHETIC_EXPIRED_DESCRIPTION",null,null);drain()
            old.submit();drain()
            val id=(screens.last() as FeedbackScreen.Issues).items.single().id
            // Fresh management capability shortly before retention expiry, not an expired PIN.
            clock.time+=WEEK-1
            val fresh=engine.open(Auth(),screens::add);drain()
            fresh.detail(id);drain()
            assertNotNull((screens.last() as FeedbackScreen.Detail).item.description)
            clock.time++
            var swept:Boolean?=null;engine.sweep{swept=it};drain()
            assertEquals(true,swept)
            val reopened=FeedbackCore(FeedbackVault(PrivateVaultFiles(dir),key),clock,Auth())
            assertTrue("restart confirms storage has expired the issue",reopened.list().isEmpty())
            val rendered=screens.last()
            assertFalse("R87-02: successful system sweep leaves expired description/reply on detail screen",
                rendered is FeedbackScreen.Detail && rendered.item.description!=null)
            fresh.close()
        } finally {dir.deleteRecursively()}
    }
}
