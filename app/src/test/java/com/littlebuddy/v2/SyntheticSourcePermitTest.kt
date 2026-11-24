package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
class SyntheticSourcePermitTest {
 private val environment=SyntheticSourceEnvironment(true,"ranchu",36,"sdk_gphone64_x86_64","x86_64")
 private val permit=SyntheticSourcePermit(CaptureInput.RECOGNITION,"01234567-0123-4567-89ab-0123456789ab",SyntheticSourcePermit.ENTER_SHA,2,100)
 @Test fun dedicatedIdentityAndBoundedFreshNonceOnly(){
  assertTrue(permit.valid(environment,101,2));assertTrue(permit.valid(environment,8099,2))
  for(e in listOf(environment.copy(enabled=false),environment.copy(hardware="oppo"),environment.copy(api=35),environment.copy(product="unknown"),environment.copy(abi="arm64-v8a")))assertFalse(permit.valid(e,101,2))
  assertFalse(permit.valid(environment,8100,2));assertFalse(permit.valid(environment,99,2));assertFalse(permit.valid(environment,101,3))
  for(p in listOf(permit.copy(nonce="old"),permit.copy(sha="other"),permit.copy(windowMs=8001),permit.copy(sampleLimit=128001)))assertFalse(p.valid(environment,101,2))
 }
}
