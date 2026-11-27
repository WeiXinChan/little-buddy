package com.littlebuddy.v2
import org.junit.Assert.*
import org.junit.Test
class ParentCornerHoldTest {
 @Test fun elsewhereCannotArmOrSlideIntoCorner(){val h=ParentCornerHold();assertFalse(h.down(100f,100f,1000,1000));h.move(999f,999f,1000,1000);assertFalse(h.fire(true))}
 @Test fun cornerFiresOnce(){val h=ParentCornerHold();assertTrue(h.down(950f,900f,1000,1000));assertTrue(h.fire(true));assertFalse(h.fire(true))}
 @Test fun leavingThenReturningDoesNotRearm(){val h=ParentCornerHold();h.down(950f,900f,1000,1000);h.move(0f,0f,1000,1000);h.move(950f,900f,1000,1000);assertFalse(h.fire(true))}
 @Test fun cancelAndFocusLossCannotFire(){val h=ParentCornerHold();h.down(950f,900f,1000,1000);h.cancel();assertFalse(h.fire(true));h.down(950f,900f,1000,1000);assertFalse(h.fire(false));assertFalse(h.fire(true))}
 @Test fun outsideOrUnlaidOutCannotArm(){val h=ParentCornerHold();assertFalse(h.down(1001f,900f,1000,1000));assertFalse(h.down(0f,0f,0,0))}
}
