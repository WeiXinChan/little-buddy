package com.littlebuddy

import org.junit.Assert.assertEquals
import org.junit.Test

class VoiceFailureTest {
    @Test fun fixedServerCodesHaveDistinctRetryMessages() {
        assertEquals("没听清，请再说一次", VoiceFailure.fromClose(4401).message)
        assertEquals("可以试着说「你好，瓦力」", VoiceFailure.fromClose(4402).message)
        assertEquals(VoiceFailure.PROTOCOL_ERROR, VoiceFailure.fromClose(1008))
        assertEquals(VoiceFailure.PROVIDER_ERROR, VoiceFailure.fromClose(1011))
        assertEquals(VoiceFailure.TIMEOUT, VoiceFailure.fromClose(1013))
        assertEquals(VoiceFailure.USER_STOPPED, VoiceFailure.fromClose(4403))
        assertEquals(VoiceFailure.CONNECTION_ERROR, VoiceFailure.fromClose(1006))
    }
}
