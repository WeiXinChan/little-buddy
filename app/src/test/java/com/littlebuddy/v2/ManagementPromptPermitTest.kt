package com.littlebuddy.v2
import org.junit.Test
import org.junit.Assert.*
class ManagementPromptPermitTest {
 @Test fun oldOrExpiredPreparationCannotPlay(){var now=0L;val p=ManagementPromptPermit{now};p.offer(1,7);assertTrue(p.valid(1,7));now=6001;assertFalse(p.valid(1,7));p.offer(2,7);assertFalse(p.valid(1,7));assertFalse(p.valid(2,8));assertTrue(p.valid(2,7))}
 @Test fun lateOldRevokeCannotEraseNewGrant(){val p=ManagementPromptPermit{0L};p.offer(1,7);p.offer(2,7);p.revoke(1,7);assertTrue(p.valid(2,7));p.revoke(2,7);assertFalse(p.valid(2,7))}
}
