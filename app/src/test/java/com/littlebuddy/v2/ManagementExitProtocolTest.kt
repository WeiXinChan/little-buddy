package com.littlebuddy.v2
import org.junit.Test
import org.junit.Assert.*
class ManagementExitProtocolTest {
 @Test fun wallClockExpiryWithoutPcmRejectsLateConfirmation(){var clock=10L;val p=ManagementExitProtocol{clock};p.reset(7);p.uncertain();p.accept("取消",100,200,300,7);p.arm(p.confirmationNonce,400,7);clock+=8001;assertNull("wall expiry despite stopped sample clock",p.accept("确认退出",500,600,700,7))}
 @Test fun staleNativeBuffersDoNotBecomeFreshAfterPrompt(){val p=fresh();p.uncertain();p.accept("取消",100,200,300,7);val marker=CaptureFreshness.marker(1000,2000,1001,400,1002);assertEquals(2000L,marker);p.arm(p.confirmationNonce,marker!!,7);assertNull(p.accept("确认退出",700,900,3000,7));assertEquals("取消",p.accept("确认退出",2100,2500,4000,7))}
 @Test fun missingOrStaleNativeTimestampKeepsConfirmationUnarmed(){assertNull(CaptureFreshness.marker(1000,2000,999,400,1001));assertNull(CaptureFreshness.marker(1000,300,1001,400,1002));val p=fresh();p.uncertain();p.accept("取消",100,200,300,7);assertNull(p.accept("确认退出",500,600,700,7))}

 private fun fresh()=ManagementExitProtocol{System.nanoTime()/1000000}.apply{reset(7)}
 @Test fun clearExitNeedsNoConfirmation(){assertEquals("取消",fresh().accept("取消",100,200,300,7))}
 @Test fun confirmationRequiresAcknowledgedPromptAndNewCapture(){val p=fresh();p.uncertain();assertEquals("确认退出提示",p.accept("取消",100,200,300,7));val n=p.confirmationNonce;assertNull(p.accept("确认退出",310,400,500,7));p.arm(n,600,7);assertNull(p.accept("确认退出",550,650,700,7));assertEquals("取消",p.accept("确认退出",701,800,900,7))}
 @Test fun duplicateAndTimeoutDoNotReopenOrExit(){val p=fresh();p.uncertain();p.accept("取消",100,200,300,7);p.arm(p.confirmationNonce,400,7);assertNull(p.accept("取消",100,200,500,7));assertNull(p.accept("取消",600,700,800,7));p.tick(130000);assertNull(p.accept("确认退出",130001,131000,132000,7));assertEquals("确认退出提示",p.accept("退出管理",132001,133000,134000,7))}
 @Test fun negationAndGenerationRevokeNonce(){val p=fresh();p.uncertain();p.accept("取消",100,200,300,7);val old=p.confirmationNonce;p.uncertain();p.arm(old,400,7);assertNull(p.accept("确认退出",500,600,700,7));p.reset(8);assertNull(p.accept("确认退出",800,900,1000,7))}
 @Test fun continueThenNormalCancelDoesNotLockUser(){val p=fresh();p.uncertain();p.accept("取消",100,200,300,7);p.arm(p.confirmationNonce,400,7);assertEquals("继续管理",p.accept("继续管理",500,600,700,7));assertEquals("取消",p.accept("取消",800,900,1000,7))}
}
