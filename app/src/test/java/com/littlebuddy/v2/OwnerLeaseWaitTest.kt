package com.littlebuddy.v2
import org.junit.Test
import org.junit.Assert.*
class OwnerLeaseWaitTest {
 @Test fun queuedOldSignalCannotConsumeReplacement(){val w=OwnerLeaseWait();val callbacks=mutableListOf<()->Unit>();var calls=0;val sub:((()->Unit)->(()->Unit))={cb->callbacks.add(cb);{}};w.begin(1,1,sub){calls+=100};w.begin(2,2,sub){calls++};callbacks[0]();assertEquals(0,calls);callbacks[1]();callbacks[1]();assertEquals(1,calls)}
 @Test fun oldStopCannotCancelNewRequest(){val w=OwnerLeaseWait();var cb:()->Unit={};var calls=0;w.begin(3,4,{cb=it;{}}){calls++};w.cancelThrough(2,9);cb();assertEquals(1,calls)}
 @Test fun oldStopCannotCancelNewLocalGeneration(){val w=OwnerLeaseWait();var cb:()->Unit={};var calls=0;w.begin(3,5,{cb=it;{}}){calls++};w.cancelThrough(3,4);cb();assertEquals(1,calls)}
 @Test fun cancelledSignalNeverResumes(){val w=OwnerLeaseWait();var cb:()->Unit={};var calls=0;w.begin(3,5,{cb=it;{}}){calls++};w.cancelThrough(3,5);cb();assertEquals(0,calls)}
}
