package com.littlebuddy.v2

import com.littlebuddy.v2.parent.PinDiagnostic
import org.junit.Assert.*
import org.junit.Test

class SessionTerminationTest {
    @Test fun onlyNormalReasonsEndCurrentScope() {
        for(reason in listOf("conversation_ended","session_expired"))
            assertTrue(SessionTermination.accepts(reason,true,true,false,true))
        for(reason in listOf("timeout","heartbeat","response","safety","","unknown"))
            assertFalse(SessionTermination.accepts(reason,true,true,false,true))
    }
    @Test fun staleManagementFocusAndClosedReject() {
        assertFalse(SessionTermination.accepts("session_expired",true,true,false,false))
        assertFalse(SessionTermination.accepts("session_expired",true,true,true,true))
        assertFalse(SessionTermination.accepts("session_expired",true,false,false,true))
        assertFalse(SessionTermination.accepts("session_expired",false,true,false,true))
    }
    @Test fun expiryNeverLearnsScopeAndEveryIdentityComponentMustMatch() {
        val scope=LocalHelpScope();val session="a".repeat(32)
        fun accept(s:String=session,t:Long=4,e:Long=2,r:Long=7)=
            SessionTermination.accepts("session_expired",true,true,false,scope.matches(s,t,e,r))
        assertFalse(accept())
        scope.bind(session,4,2,7)
        assertTrue(accept())
        assertFalse(accept(s="b".repeat(32)));assertFalse(accept(t=5))
        assertFalse(accept(e=3));assertFalse(accept(r=8))
        scope.clear();assertFalse(accept())
    }
    @Test fun terminalConsumptionIsIdempotentAndOldScopeCannotEndReplacement() {
        var active=true;var ended=0
        repeat(2){if(SessionTermination.accepts("session_expired",active,true,false,true)){active=false;ended++}}
        assertEquals(1,ended)
        assertFalse(SessionTermination.accepts("session_expired",true,true,false,false))
    }
    @Test fun whitelistHasNoWireTextAndTimeoutIsFailureNotEnd() {
        val expected=mapOf("timeout" to PinDiagnostic.FailSource.SERVER_TIMEOUT,"quota" to PinDiagnostic.FailSource.SERVER_QUOTA,
            "voice" to PinDiagnostic.FailSource.SERVER_VOICE,"safety" to PinDiagnostic.FailSource.SERVER_SAFETY,
            "auth" to PinDiagnostic.FailSource.SERVER_AUTH,"unavailable" to PinDiagnostic.FailSource.SERVER_UNAVAILABLE)
        expected.forEach{(wire,source)->assertEquals(source,PinDiagnostic.failSource(ServerFailure.classify(wire).localCode))}
        listOf("secret arbitrary body","TIMEOUT","timeout\n", "", "response_timeout").forEach{
            assertEquals(ServerFailure.UNKNOWN,ServerFailure.classify(it))
        }
        assertFalse(SessionTermination.accepts("timeout",true,true,false,true))
    }
}
