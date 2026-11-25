package com.littlebuddy.v2.feedback

import java.nio.file.Files
import javax.crypto.KeyGenerator
import org.junit.Assert.*
import org.junit.Test

class Review40RepairProbe {
    private class Queue: FeedbackQueue {
        val jobs=ArrayDeque<()->Unit>()
        override fun post(action:()->Unit) {jobs.addLast(action)}
        fun drain() {while(jobs.isNotEmpty()) jobs.removeFirst()()}
    }
    private class Clock(var t:Long=1000):FeedbackClock {override fun now()=t}
    private class Auth:FeedbackPageAuthority {
        var epoch=0;var alive=true
        private class Intent(val epoch:Int):ParentIntent
        override fun current()=alive
        override fun invalidate(){epoch++}
        override fun close(){alive=false;epoch++}
        override fun prepare(operation:Operation,digest:String):ParentIntent?=if(alive)Intent(epoch)else null
        override fun accept(intent:ParentIntent,operation:Operation,digest:String,acceptance:()->Unit):Boolean {
            if(!alive || (intent as Intent).epoch!=epoch)return false
            acceptance();return true
        }
    }
    private class FaultFiles(val base:VaultFiles):VaultFiles {
        var fail=false
        override fun read(name:String)=base.read(name)
        override fun remove(name:String)=base.remove(name)
        override fun replace(name:String,bytes:ByteArray) {
            if(fail)throw java.io.IOException("synthetic disk failure")
            base.replace(name,bytes)
        }
    }
    @Test fun failedExpirySweepMustNotDeliverQueuedExpiredDetail() {
        val dir=Files.createTempDirectory("qa40-repair-fault-").toFile()
        try {
            val key=KeyGenerator.getInstance("AES").apply{init(256)}.generateKey()
            val clock=Clock();val files=FaultFiles(PrivateVaultFiles(dir));val work=Queue();val ui=Queue()
            val screens=mutableListOf<FeedbackScreen>()
            val provider=object:FeedbackProvider {
                override fun available()=true
                override fun submit(idempotencyKey:String,payload:FeedbackPayload,admit:()->Boolean):SubmitReceipt {
                    check(admit());return SubmitReceipt(clock.t)
                }
                override fun withdraw(idempotencyKey:String)=DeleteReceipt(clock.t,true)
            }
            val engine=FeedbackEngine(work,ui,{auth->FeedbackCore(FeedbackVault(files,key),clock,auth,provider)},{true})
            fun drain(){work.drain();ui.drain()}
            val first=engine.open(Auth(),screens::add);drain()
            first.preview(Category.OTHER,"QA40_SYNTHETIC_FAULT_BODY",null,null);drain();first.submit();drain()
            val id=(screens.last() as FeedbackScreen.Issues).items.single().id
            clock.t+=WEEK-1
            val fresh=engine.open(Auth(),screens::add);drain()
            fresh.detail(id);work.drain() // sensitive detail pending; UI queue blocked
            val before=screens.size
            clock.t++;files.fail=true
            var success:Boolean?=null;engine.sweep{success=it};work.drain()
            assertEquals(false,success)
            files.fail=false
            val restarted=FeedbackCore(FeedbackVault(files,key),clock,Auth())
            assertTrue("restart independently expires the actual vault",restarted.list().isEmpty())
            ui.drain()
            assertTrue("a bounded failure notice must still appear",screens.last() is FeedbackScreen.Notice || screens.last()===FeedbackScreen.Locked)
            assertFalse("R87-03: failed expiry sweep allows queued expired detail to render before the error notice",
                screens.drop(before).any{it is FeedbackScreen.Detail && it.item.description!=null})
            fresh.close()
        }finally{dir.deleteRecursively()}
    }
}
