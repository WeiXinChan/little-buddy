package com.littlebuddy.v2

import com.littlebuddy.v2.parent.*
import org.junit.Assert.*
import org.junit.After
import org.junit.Test
import java.util.ArrayDeque

class RuntimeRetryGateTest {
    @After fun clear(){PinDiagnostic.install(null)}
    @Test fun technicalFailureStopsHelpReturnAndLifecycleRetryLoop(){
        val gate=RuntimeRetryGate();var starts=0
        fun resume(){if(gate.automaticAllowed)starts++}
        resume();assertTrue(gate.technicalFailure())
        repeat(20){resume();assertFalse(gate.technicalFailure())}
        assertEquals(1,starts)
    }
    @Test fun onlyExplicitParentExitAllowsOneNewAttempt(){
        val gate=RuntimeRetryGate();gate.technicalFailure();assertFalse(gate.automaticAllowed)
        gate.explicitParentRetry();assertTrue(gate.automaticAllowed)
        assertTrue(gate.technicalFailure());assertFalse(gate.automaticAllowed)
    }
    @Test fun realSafetyHelpDoesNotBecomeTechnicalFailure(){
        val gate=RuntimeRetryGate();val scope=LocalHelpScope();val session="a".repeat(32)
        scope.bind(session,0,0,0)
        assertEquals(LocalHelpReason.CONTENT_BLOCKED,scope.accept(session,0,0,0,1,"safety_support_v1","content_blocked"))
        assertTrue(gate.automaticAllowed)
        assertNull(scope.accept(session,0,0,0,1,"safety_support_v1","content_blocked"))
    }
    @Test fun unboundOrStaleSafetyFrameCannotPresentTrustedHelp(){
        val scope=LocalHelpScope();val session="a".repeat(32)
        assertNull(scope.accept(session,0,0,0,1,"safety_support_v1","content_blocked"))
        scope.bind(session,0,1,0)
        assertNull(scope.accept(session,0,0,0,1,"safety_support_v1","content_blocked"))
    }
    @Test fun exceptionClassificationUsesClosedVocabularyNotMessages(){
        val seen=mutableListOf<PinDiagnostic.Reason>()
        PinDiagnostic.install{_,_,_,r->seen.add(r)}
        PinDiagnostic.runtimeError(PinDiagnostic.Stage.WSS,javax.net.ssl.SSLHandshakeException("synthetic sensitive text"))
        PinDiagnostic.runtimeError(PinDiagnostic.Stage.WSS,java.net.SocketTimeoutException("synthetic sensitive text"))
        assertEquals(listOf(PinDiagnostic.Reason.TLS_HANDSHAKE,PinDiagnostic.Reason.SITE_UNKNOWN,PinDiagnostic.Reason.TLS_HANDSHAKE,
            PinDiagnostic.Reason.TIMEOUT,PinDiagnostic.Reason.SITE_UNKNOWN,PinDiagnostic.Reason.TIMEOUT),seen)
    }
    private class Rig {
        var time=0L;var record=ParentRecord(ByteArray(16),ByteArray(32));var savedSignals=0
        val work=ArrayDeque<()->Unit>();val ui=ArrayDeque<()->Unit>()
        val d=ParentDomain(object:ParentStore{
            override fun read()=record
            override fun write(next:ParentRecord,allowed:()->Boolean){check(allowed());record=next}
        },{time},{},object:OwnerProof{override fun consume(challenge:OwnerChallenge)=true},"synthetic-binding",object:PinHasher(){override fun derive(pin:CharArray,salt:ByteArray)=ByteArray(32)})
        val model=ParentPanelModel({d},{work.add(it)},{ui.add(it)},{},{},configurationSaved={savedSignals++})
        fun drain(){while(work.isNotEmpty()||ui.isNotEmpty()){work.pollFirst()?.invoke();ui.pollFirst()?.invoke()}}
        fun ready(){model.open();drain();model.verify("123456".toCharArray());drain();model.prepareOwner(OwnerOperation.PROVISION_ENDPOINT){true};drain()}
    }
    @Test fun currentSuccessfulCommitNotifiesBeforeLockedRender(){
        val r=Rig();r.ready();r.model.importConnection("wss://127.0.0.1:19483/v2/voice","a".repeat(32).toCharArray(),"v2-device-oppo");r.drain()
        assertEquals(1,r.savedSignals);assertEquals(PanelNotice.CONNECTION_SAVED,r.model.state.notice)
    }
    @Test fun cancelledOldCommitCannotUpdateNewPageNotice(){
        val r=Rig();r.ready();r.model.importConnection("wss://127.0.0.1:19483/v2/voice","a".repeat(32).toCharArray(),"v2-device-oppo")
        r.model.pause();r.drain();assertEquals(0,r.savedSignals);assertNull(r.record.connection)
    }
}
