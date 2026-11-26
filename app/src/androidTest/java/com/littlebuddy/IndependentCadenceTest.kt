package com.littlebuddy
import org.junit.Test
import org.junit.Assert.*
class IndependentCadenceTest {
 private class Port(val cross:Boolean):CadencePort {
  var monoCalls=0;var now=0L;var calls=0;var scratch:ShortArray?=null
  override fun monoNs():Long { monoCalls++;if(cross && monoCalls==4)now=CadenceDiagnostic.WINDOW_NS;return now }
  override fun bootNs()=now
  override fun allowed()=true
  override fun read(samples:ShortArray,count:Int):Int {scratch=samples;samples.fill(9);return count}
  override fun timestamp():StartupApiSample {calls++;return StartupApiSample(-3)}
  override fun pause(){}
 }
 @Test fun noNewTimestampAtAlreadyExpiredApiBefore(){
  val p=Port(true);val r=CadenceObservation();runCatching{CadenceDiagnostic.run(p,r)}
  println("deadline_pre_api calls=${p.calls} late=${r.lateCalls} elapsed=${r.elapsedNs}")
  assertTrue(p.scratch!!.all{it==0.toShort()});assertEquals(0,p.calls)
 }
 @Test fun sampleCapAndScratchAreBounded(){
  val p=Port(false);val r=CadenceObservation();CadenceDiagnostic.run(p,r)
  assertEquals(64000L,r.samples);assertEquals(199,p.calls);assertEquals("SAMPLE_LIMIT",r.terminal)
  assertTrue(p.scratch!!.all{it==0.toShort()})
 }
}
