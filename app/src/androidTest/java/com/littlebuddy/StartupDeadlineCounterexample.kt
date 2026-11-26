package com.littlebuddy
import org.junit.Assert.*
import org.junit.Test

class StartupDeadlineCounterexample {
    @Test fun successReturnedAfterWindowMustNotCountAsWithinWindow() {
        var now=0L
        val port=object:StartupPort {
            override fun nowMs()=now
            override fun allowed()=true
            override fun read(samples:ShortArray,count:Int)=0
            override fun timestamp():StartupApiSample {
                if(now<990)return StartupApiSample(-3)
                now=1010 // API began at990ms but returned20ms later.
                return StartupApiSample(0,16160,1010000000)
            }
            override fun pause(ms:Long){now+=ms}
        }
        val a=StartupObservation(StartupMode.TIMESTAMP_ONLY)
        StartupDiagnostic.run(port,a)
        assertEquals(1010L,a.firstSuccessMs) // raw late observation must stay available
        val b=StartupObservation(StartupMode.READ_THEN_TIMESTAMP)
        val actual=StartupDiagnostic.interpretation(a,b)
        println("late-success: raw_ms=${a.firstSuccessMs},well_formed_ms=${a.firstWellFormedMs},actual=$actual")
        assertEquals("late SUCCESS is not in-window availability",
            "UNAVAILABLE_IN_TWO_WINDOWS_NOT_PERMANENT_UNSUPPORTED",actual)
    }
    @Test fun readReturningPastDeadlineMustNotIssueAnotherTimestampCall() {
        var now=0L;var calls=0
        val port=object:StartupPort {
            override fun nowMs()=now
            override fun allowed()=true
            override fun read(samples:ShortArray,count:Int):Int {
                samples.fill(7);now=1001 // one blocked read consumes the whole window
                return count
            }
            override fun timestamp():StartupApiSample {calls++;return StartupApiSample(-3)}
            override fun pause(ms:Long){now+=ms}
        }
        val result=StartupObservation(StartupMode.READ_THEN_TIMESTAMP)
        StartupDiagnostic.run(port,result)
        println("post-read: elapsed_ms=${result.elapsedMs},timestamp_calls=$calls")
        assertEquals("must observe expired deadline before starting a new timestamp API",0,calls)
    }
}
