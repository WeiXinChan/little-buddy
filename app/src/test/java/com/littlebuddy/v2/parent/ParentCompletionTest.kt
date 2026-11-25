package com.littlebuddy.v2.parent

import com.littlebuddy.v2.LocalHelpScope
import org.junit.Assert.*
import org.junit.Test
import java.security.KeyPairGenerator
import java.security.Signature
import java.util.ArrayDeque

/** Synthetic JCA signer models the issuer boundary; never claims Android credential execution. */
class ParentCompletionTest {
    private class Store : ParentStore {
        var bytes: ByteArray? = null; var before: (() -> Unit)? = null
        override fun read() = bytes?.let(ParentCodec::decode)
        override fun write(record: ParentRecord, authorized: () -> Boolean) {
            before?.invoke(); check(authorized()); bytes = ParentCodec.encode(record)
        }
    }
    private class Rig {
        var now = 100L
        val keys = KeyPairGenerator.getInstance("EC").apply { initialize(256) }.generateKeyPair()
        val receipt = OwnerReceipt(keys.public, "test-system-key", { now })
        val store = Store()
        val domain = ParentDomain(store, { now }, {}, receipt, "test-system-key")
        fun approve(p: OwnerChallenge) = receipt.approve(p) { message -> Signature.getInstance("SHA256withECDSA").run {
            initSign(keys.private); update(message); sign()
        } }
        fun proof(op: OwnerOperation, page: Long) = domain.beginOwnerOperation(op, page)!!.also { check(approve(it)) }
        fun initialize() { val page = domain.enterPage(); check(domain.replacePin("012345".toCharArray(), proof(OwnerOperation.INITIALIZE_PIN,page),page)) }
        fun grant(): ParentDomain.Grant { val page = domain.enterPage(); return domain.verify("012345".toCharArray(),page)!! }
    }
    @Test fun signedReceiptIsBoundAndOneShot() {
        val r=Rig();val p=OwnerChallenge(ByteArray(32),"test-system-key",OwnerOperation.INITIALIZE_PIN,1000)
        assertTrue(r.approve(p));assertTrue(r.receipt.consume(p));assertFalse(r.receipt.consume(p))
    }
    @Test fun aDifferentSigningKeyCannotIssueOwnerProof() {
        val r=Rig();val other=KeyPairGenerator.getInstance("EC").apply { initialize(256) }.generateKeyPair()
        val p=OwnerChallenge(ByteArray(32),"test-system-key",OwnerOperation.RESET_PIN,1000)
        assertFalse(r.receipt.approve(p) { message -> Signature.getInstance("SHA256withECDSA").run {
            initSign(other.private);update(message);sign()
        } });assertFalse(r.receipt.consume(p))
    }
    @Test fun changedNonceAndEqualDeadlineReject() {
        val r=Rig();val p=OwnerChallenge(ByteArray(32),"test-system-key",OwnerOperation.RESET_PIN,1000)
        assertTrue(r.approve(p));p.nonce[0]=1;assertFalse(r.receipt.consume(p))
        val next=OwnerChallenge(ByteArray(32),"test-system-key",OwnerOperation.RESET_PIN,1000)
        assertTrue(r.approve(next));r.now=1000;assertFalse(r.receipt.consume(next))
    }
    @Test fun discardedOldReceiptNeverConsumesNewReceipt() {
        val r=Rig();val old=OwnerChallenge(ByteArray(32),"test-system-key",OwnerOperation.RESET_PIN,1000)
        val next=OwnerChallenge(ByteArray(32),"test-system-key",OwnerOperation.PROVISION_ENDPOINT,1000)
        assertTrue(r.approve(old));assertTrue(r.approve(next));r.receipt.discard(old)
        assertFalse(r.receipt.consume(old));assertTrue(r.receipt.consume(next))
    }
    @Test fun firstPinNeedsSignedSystemOperation() {
        val r=Rig();val page=r.domain.enterPage();val p=r.domain.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN,page)!!
        val pin="012345".toCharArray();assertFalse(r.domain.replacePin(pin,p,page));assertNull(r.store.bytes)
        assertTrue(pin.all { it=='\u0000' });r.initialize();assertNotNull(r.store.bytes)
    }
    @Test fun settingsConnectionAndPinRecoveryPreserveEachOther() {
        val r=Rig();r.initialize();assertTrue(r.domain.saveSettings(r.grant(),ParentPlaybackSettings(42,90,180)))
        var page=r.domain.enterPage();assertTrue(r.domain.provisionConnection(r.proof(OwnerOperation.PROVISION_ENDPOINT,page),page,
            ParentConnection("wss://example.invalid/v2/voice","a".repeat(32))))
        page=r.domain.enterPage();assertTrue(r.domain.replacePin("654321".toCharArray(),r.proof(OwnerOperation.RESET_PIN,page),page))
        val config=r.domain.childConfiguration()!!
        assertEquals(42,config.playback.volume);assertEquals(90,config.playback.rate);assertEquals(180,config.playback.durationSeconds)
        assertEquals("wss://example.invalid/v2/voice",config.connection!!.address)
        assertNull(r.domain.verify("012345".toCharArray(),r.domain.enterPage()))
        assertNotNull(r.domain.verify("654321".toCharArray(),r.domain.enterPage()))
    }
    @Test fun revokeDuringSettingsAndConnectionPreparationRejectsFinalWrite() {
        val r=Rig();r.initialize();val g=r.grant();r.store.before={r.domain.revoke()}
        assertFalse(r.domain.saveSettings(g,ParentPlaybackSettings(99,115,60)))
        assertEquals(60,r.store.read()!!.volumeLimit);r.store.before=null
        val page=r.domain.enterPage();val proof=r.proof(OwnerOperation.PROVISION_ENDPOINT,page)
        r.store.before={r.domain.revoke()}
        assertFalse(r.domain.provisionConnection(proof,page,ParentConnection("wss://example.invalid/v2/voice","a".repeat(32))))
        assertNull(r.store.read()!!.connection)
    }
    @Test fun wrongOperationAndForgedChallengeCannotProvisionConnection() {
        val r=Rig();r.initialize();val page=r.domain.enterPage();val proof=r.proof(OwnerOperation.RESET_PIN,page)
        assertFalse(r.domain.provisionConnection(proof,page,ParentConnection("wss://example.invalid/v2/voice","a".repeat(32))))
        val forged=OwnerChallenge(proof.nonce.copyOf(),proof.deviceBinding,OwnerOperation.PROVISION_ENDPOINT,proof.expiresAt)
        assertFalse(r.domain.provisionConnection(forged,page,ParentConnection("wss://example.invalid/v2/voice","a".repeat(32))))
    }
    @Test fun oldV1RecordStillDecodesAndExtendedRecordRejectsTrailingBytes() {
        val old=ParentRecord(ByteArray(16),ByteArray(32));val bytes=ParentCodec.encode(old)
        assertEquals(72,bytes.size);assertEquals(100,ParentCodec.decode(bytes).speechRate)
        val extended=old.updated(speechRate=90,durationSeconds=120)
        assertEquals(90,ParentCodec.decode(ParentCodec.encode(extended)).speechRate)
        try {ParentCodec.decode(ParentCodec.encode(extended)+byteArrayOf(0));fail()}catch(_:Exception){}
    }
    @Test fun unsafeAddressesAndOutOfRangePlaybackSettingsReject() {
        for (uri in listOf("ws://example.invalid/v2/voice","wss://user@example.invalid/v2/voice",
            "wss://example.invalid/v2/voice?token=x","wss://example.invalid/other")) {
            try {ParentConnection(uri,"a".repeat(32));fail(uri)}catch(_:IllegalArgumentException){}
        }
        try {ParentPlaybackSettings(101,100,600);fail()}catch(_:IllegalArgumentException){}
        try {ParentPlaybackSettings(50,116,600);fail()}catch(_:IllegalArgumentException){}
        try {ParentPlaybackSettings(50,100,601);fail()}catch(_:IllegalArgumentException){}
    }
    @Test fun modelOwnerPinIsReachableButHomeBeforeQueuedSaveRejectsAndWipes() {
        val r=Rig();val work=ArrayDeque<()->Unit>();val ui=ArrayDeque<()->Unit>()
        val model=ParentPanelModel({r.domain},{work.add(it)},{ui.add(it)},{},{},ownerDiscard=r.receipt::discard)
        fun drain(){while(work.isNotEmpty()||ui.isNotEmpty()){while(work.isNotEmpty())work.removeFirst()();while(ui.isNotEmpty())ui.removeFirst()()}}
        model.open();drain();model.prepareOwner(OwnerOperation.INITIALIZE_PIN,r::approve);drain()
        assertEquals(PanelMode.OWNER_PIN,model.state.mode)
        val first="012345".toCharArray();val second=first.copyOf();model.setOwnerPin(first,second);model.pause();drain()
        assertNull(r.store.bytes);assertTrue(first.all{it=='\u0000'}&&second.all{it=='\u0000'})
        assertFalse(model.userAction(model.viewToken){fail("background")})
        model.open();drain();model.prepareOwner(OwnerOperation.INITIALIZE_PIN,r::approve);drain()
        model.setOwnerPin("012345".toCharArray(),"012345".toCharArray());drain()
        assertEquals(PanelMode.VERIFY,model.state.mode);assertNotNull(r.store.bytes)
    }
    @Test fun helpNeverLearnsAuthorityFromFailureAndRejectsDuplicatesOrForeignScope() {
        val gate=LocalHelpScope();val id="a".repeat(32)
        assertNull(gate.accept(id,1,0,2,1,"safety_support_v1","review_unavailable"))
        gate.bind(id,1,0,2)
        assertNull(gate.accept(id,2,0,2,1,"safety_support_v1","review_unavailable"))
        assertNull(gate.accept(id,1,0,2,2,"safety_support_v1","review_unavailable"))
        assertNotNull(gate.accept(id,1,0,2,1,"safety_support_v1","review_unavailable"))
        gate.bind(id,1,0,2);assertNull(gate.accept(id,1,0,2,1,"safety_support_v1","review_unavailable"))
        gate.clear();assertNull(gate.accept(id,1,0,2,1,"safety_support_v1","content_blocked"))
    }
    @Test fun issuerRejectsForeignBindingAndExpiryDuringSigning() {
        val r=Rig();val foreign=OwnerChallenge(ByteArray(32),"other-device",OwnerOperation.RESET_PIN,200)
        assertFalse(r.approve(foreign))
        val p=OwnerChallenge(ByteArray(32),"test-system-key",OwnerOperation.RESET_PIN,200)
        assertFalse(r.receipt.approve(p) { message ->
            val bytes=Signature.getInstance("SHA256withECDSA").run {initSign(r.keys.private);update(message);sign()}
            r.now=200;bytes
        });assertFalse(r.receipt.consume(p))
    }
    @Test fun oldOwnerUiCallbackCannotRestoreAfterHome() {
        val r=Rig();val work=ArrayDeque<()->Unit>();val ui=ArrayDeque<()->Unit>()
        val model=ParentPanelModel({r.domain},{work.add(it)},{ui.add(it)},{},{},ownerDiscard=r.receipt::discard)
        model.open();work.removeFirst()();ui.removeFirst()()
        model.prepareOwner(OwnerOperation.INITIALIZE_PIN,r::approve);work.removeFirst()()
        model.pause();ui.removeFirst()()
        assertEquals(PanelMode.VERIFY,model.state.mode)
        assertFalse(model.userAction(model.viewToken){fail()});assertNull(r.store.bytes)
    }
    @Test fun durationIsExactAndDuplicateWakeDoesNotRenew() {
        var time=100L;val budget=com.littlebuddy.v2.PlaybackBudget({time},60)
        time=10000;assertFalse(budget.expired());budget.begin()
        time+=59000;budget.begin();assertFalse(budget.expired());time+=1000;assertTrue(budget.expired())
    }
    @Test fun monotonicRegressionFailsClosed() {
        var time=100L;val budget=com.littlebuddy.v2.PlaybackBudget({time},60)
        budget.begin();time--;assertTrue(budget.expired())
    }

    @Test fun childStartupRefusesMissingOrChangedDurableRecord() {
        val r=Rig();r.initialize();r.store.bytes=null
        assertNull(r.domain.childConfiguration());assertEquals(ParentDomain.State.QUARANTINED,r.domain.state())
        val other=Rig();other.initialize();val original=other.store.read()!!
        other.store.bytes=ParentCodec.encode(original.updated(volumeLimit=99))
        assertNull(other.domain.childConfiguration());assertEquals(ParentDomain.State.QUARANTINED,other.domain.state())
    }

}
