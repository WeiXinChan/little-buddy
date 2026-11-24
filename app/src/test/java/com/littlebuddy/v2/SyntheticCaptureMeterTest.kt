package com.littlebuddy.v2
import org.junit.Test
import org.junit.Assert.*
class SyntheticCaptureMeterTest {
 @Test fun fullIntervalEnergyDoesNotMissMiddleSpeech(){val m=SyntheticCaptureMeter();repeat(24){assertNull(m.accept(ShortArray(320),320))};assertNull(m.accept(ShortArray(320){1000},320));repeat(24){assertNull(m.accept(ShortArray(320),320))};val s=m.accept(ShortArray(320),320)!!;assertTrue(s.contains("end=16000"));assertTrue(s.contains("nonzero=320"));assertTrue(s.contains("peak=1000"));assertTrue(s.contains("rms=141"))}
 @Test fun aggregateResetsAndNeverRetainsWaveform(){val m=SyntheticCaptureMeter();repeat(50){m.accept(ShortArray(320){100},320)};var last:String?=null;repeat(50){last=m.accept(ShortArray(320),320)};assertTrue(last!!.contains("end=32000 count=16000 rms=0 nonzero=0 peak=0"))}
}
