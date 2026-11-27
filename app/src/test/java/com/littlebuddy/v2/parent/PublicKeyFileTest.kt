package com.littlebuddy.v2.parent

import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.security.KeyPairGenerator
import java.security.interfaces.RSAPublicKey
import java.util.Base64
import java.util.ArrayDeque

class PublicKeyFileTest {
    private val key: String get() = PUBLIC
    private class Output : PublicKeyFile.Destination {
        var bytes: ByteArray? = null; var published=false; var deleted=false
        var beforeWrite: () -> Unit = {}; var beforePublish: () -> Unit = {}; var failDelete=false
        override fun write(bytes: ByteArray) { beforeWrite(); this.bytes=bytes.copyOf() }
        override fun publish() { beforePublish();published=true }
        override fun delete() { if(failDelete)error("synthetic cleanup");deleted=true;bytes=null }
    }
    @Test fun exactPublicLineAndNewlineOnly() {
        val output=Output();val request=PublicKeyFile { 0 };assertTrue(request.release(key))
        assertEquals(PublicKeyFile.Result.SAVED,request.save { output })
        assertEquals(key+"\n",String(output.bytes!!,Charsets.US_ASCII))
        assertTrue(output.published);assertFalse(output.deleted)
    }
    @Test fun privateTokenCommentsAndExtraFieldsRefuse() {
        for (bad in listOf("PRIVATE KEY", "Bearer secret",key+"\n",key+" comment",key+"\nssh-rsa AAAA")) {
            try {PublicKeyFile.encode(bad);fail("unexpected non-public format")}catch(_:IllegalArgumentException){}
        }
        val raw=Base64.getDecoder().decode(key.substring(8))+byteArrayOf(0)
        try{PublicKeyFile.encode("ssh-rsa "+Base64.getEncoder().encodeToString(raw));fail()}catch(_:IllegalArgumentException){}
    }
    @Test fun noAdmissionNeverCreatesFile() {
        var creates=0;val request=PublicKeyFile{0}
        assertEquals(PublicKeyFile.Result.CANCELLED,request.save{creates++;Output()});assertEquals(0,creates)
    }
    @Test fun cancellationBeforeWriteCreatesNothingAndCannotReleaseLate() {
        val r=PublicKeyFile{0};r.cancel();assertFalse(r.release(key))
        assertEquals(PublicKeyFile.Result.CANCELLED,r.save{fail("no create");Output()})
    }
    @Test fun duplicateReleaseAndSecondSaveRefuse() {
        val r=PublicKeyFile{0};assertTrue(r.release(key));assertFalse(r.release(key))
        assertEquals(PublicKeyFile.Result.SAVED,r.save{Output()})
        assertEquals(PublicKeyFile.Result.CANCELLED,r.save{fail();Output()})
    }
    @Test fun cancelInsideCreateDeletesOwnRow() {
        val r=PublicKeyFile{0};r.release(key);val o=Output()
        assertEquals(PublicKeyFile.Result.CANCELLED,r.save{r.cancel();o});assertTrue(o.deleted);assertFalse(o.published)
    }
    @Test fun writeExceptionDeletesPartialOutput() {
        val r=PublicKeyFile{0};r.release(key);val o=Output().apply{beforeWrite={error("synthetic write")}}
        assertEquals(PublicKeyFile.Result.FAILED,r.save{o});assertTrue(o.deleted)
    }
    @Test fun cancelDuringWriteDeletesBeforePublish() {
        val r=PublicKeyFile{0};r.release(key);val o=Output().apply{beforeWrite={r.cancel()}}
        assertEquals(PublicKeyFile.Result.CANCELLED,r.save{o});assertTrue(o.deleted);assertFalse(o.published)
    }
    @Test fun cancelDuringPublishDeletesNewObject() {
        val r=PublicKeyFile{0};r.release(key);val o=Output().apply{beforePublish={r.cancel()}}
        assertEquals(PublicKeyFile.Result.CANCELLED,r.save{o});assertTrue(o.deleted)
    }
    @Test fun cleanupFailureCannotMasqueradeAsCancelOrSuccess() {
        val r=PublicKeyFile{0};r.release(key);val o=Output().apply{beforePublish={r.cancel()};failDelete=true}
        assertEquals(PublicKeyFile.Result.CLEANUP_FAILED,r.save{o})
    }
    @Test fun fixedExpiryClearsPendingAndNoFile() {
        var now=0L;val r=PublicKeyFile{now};r.release(key);now=120000
        assertEquals(PublicKeyFile.Result.CANCELLED,r.save{fail();Output()})
        assertFalse(r.release(key))
    }
    @Test fun cancelAfterCommitKeepsCompletedPublicFile() {
        val r=PublicKeyFile{0};r.release(key);val o=Output();assertEquals(PublicKeyFile.Result.SAVED,r.save{o})
        r.cancel();assertFalse(o.deleted);assertEquals(key+"\n",String(o.bytes!!))
    }
    private class Rig {
        var now=0L;var record:ParentRecord?=null
        val domain=ParentDomain(object:ParentStore{
            override fun read()=record
            override fun write(value:ParentRecord,authorized:()->Boolean){check(authorized());record=value}
        },{now},{},object:OwnerProof{override fun consume(challenge:OwnerChallenge)=true},"public-file-test",
          object:PinHasher(){override fun derive(pin:CharArray,salt:ByteArray)=ByteArray(32)})
        val work=ArrayDeque<()->Unit>();val ui=ArrayDeque<()->Unit>()
        val model=ParentPanelModel({domain},{work.add(it)},{ui.add(it)},{},{})
        init {
            val page=domain.enterPage();check(domain.replacePin("123456".toCharArray(),domain.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN,page)!!,page))
            model.open();drain();model.verify("123456".toCharArray());drain();assertEquals(PanelMode.SETTINGS,model.state.mode)
        }
        fun drain(){while(work.isNotEmpty()||ui.isNotEmpty()){while(work.isNotEmpty())work.removeFirst()();while(ui.isNotEmpty())ui.removeFirst()()}}
    }
    @Test fun productionModelFinalGateReleasesOnlyCurrentGrantPublicMaterial() {
        val r=Rig();val file=PublicKeyFile{r.now}
        r.model.exportTransportKey({key}){file.release(it)};r.drain()
        val o=Output();assertEquals(PublicKeyFile.Result.SAVED,file.save{o});assertEquals(key+"\n",String(o.bytes!!))
    }
    @Test fun revokedDuringKeyLoadCannotReleaseOrCreateFile() {
        val r=Rig();val file=PublicKeyFile{r.now}
        r.model.exportTransportKey({r.domain.revoke();key}){file.release(it)};r.drain()
        assertEquals(PublicKeyFile.Result.CANCELLED,file.save{fail();Output()})
    }
    @Test fun homeAndNewPageCannotBorrowQueuedExport() {
        val r=Rig();val file=PublicKeyFile{r.now}
        r.model.exportTransportKey({key}){file.release(it)};r.work.removeFirst()()
        r.model.pause();r.model.open();r.drain();r.model.verify("123456".toCharArray());r.drain()
        assertEquals(PublicKeyFile.Result.CANCELLED,file.save{fail();Output()})
    }
    @Test fun expiredGrantCannotReleaseEvenWithSuccessfulKeyRead() {
        val r=Rig();val file=PublicKeyFile{r.now}
        r.model.exportTransportKey({r.now+=120000;key}){file.release(it)};r.drain()
        assertEquals(PublicKeyFile.Result.CANCELLED,file.save{fail();Output()})
    }
    @Test fun publicOnlyPickerContinuesWithoutRestoringParentAuthority() {
        val r=Rig();val file=PublicKeyFile{r.now}
        r.model.exportTransportKey({key}){file.release(it)};r.drain();r.model.pause()
        assertEquals(ParentDomain.State.LOCKED,r.domain.state())
        assertEquals(PublicKeyFile.Result.SAVED,file.save{Output()})
        assertEquals(PanelMode.VERIFY,r.model.state.mode)
        assertEquals(ParentDomain.State.LOCKED,r.domain.state())
    }
    @Test fun keyReadFailureReportsPromptlyWithoutFileOrExceptionText() {
        val r=Rig();val file=PublicKeyFile{r.now};var rejected=0;var published=0
        r.model.exportTransportKey({error("synthetic credential-shaped exception")},{published++},{rejected++;file.cancel()})
        r.drain();assertEquals(1,rejected);assertEquals(0,published)
        assertEquals(PublicKeyFile.Result.CANCELLED,file.save{fail();Output()})
    }
    @Test fun expiryInsideWriteDeletesInsteadOfPublishing() {
        var now=0L;val file=PublicKeyFile{now};file.release(key)
        val output=Output().apply{beforeWrite={now=120000}}
        assertEquals(PublicKeyFile.Result.CANCELLED,file.save{output});assertTrue(output.deleted);assertFalse(output.published)
    }
    @Test fun workerBufferIsClearedAfterCompletion() {
        val file=PublicKeyFile{0};file.release(key);var seen:ByteArray?=null
        val output=object:PublicKeyFile.Destination {
            override fun write(bytes:ByteArray){seen=bytes}
            override fun publish(){}
            override fun delete(){}
        }
        assertEquals(PublicKeyFile.Result.SAVED,file.save{output});assertTrue(seen!!.all{it==0.toByte()})
    }
    companion object {
        private val PUBLIC:String by lazy {
            val rsa=KeyPairGenerator.getInstance("RSA").apply{initialize(2048)}.generateKeyPair().public as RSAPublicKey
            val bytes=ByteArrayOutputStream();DataOutputStream(bytes).use{out->
                for (field in listOf("ssh-rsa".toByteArray(),rsa.publicExponent.toByteArray(),rsa.modulus.toByteArray())){out.writeInt(field.size);out.write(field)}
            };"ssh-rsa "+Base64.getEncoder().encodeToString(bytes.toByteArray())
        }
    }
}
