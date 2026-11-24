package com.littlebuddy.v2
import org.junit.Test
import org.junit.Assert.*
class PendingConnectionTest {
 @Test fun lateOldStopCannotEraseNewerRequest(){val p=PendingConnection<String>();p.offer(5,9,"new");p.invalidateThrough(4);assertEquals("new",p.take(5,{true},true))}
 @Test fun disposalAfterThreeSecondsAnd317msConsumesOnce(){val p=PendingConnection<String>();var clock=0L;p.offer(4,9,"synthetic");clock+=3000;assertNull(p.take(4,{it==9L},false));clock+=317;assertEquals(3317L,clock);assertEquals("synthetic",p.take(4,{it==9L},true));assertNull(p.take(4,{true},true))}
 @Test fun homeAndGenerationRevokeBeforeLateCompletion(){val p=PendingConnection<String>();p.offer(4,9,"synthetic");assertNull(p.take(5,{false},true));assertFalse(p.present)}
 @Test fun newRequestReplacesOldPayload(){val p=PendingConnection<String>();p.offer(4,9,"old");p.offer(5,9,"new");assertEquals("new",p.take(5,{true},true))}
 @Test fun releaseWithoutWorkerAndLeaseNeverConsumes(){val p=PendingConnection<String>();p.offer(4,9,"synthetic");repeat(4){assertNull(p.take(4,{true},false))};p.invalidate();assertNull(p.take(4,{true},true))}
}
