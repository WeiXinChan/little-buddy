package com.littlebuddy.v2
internal fun wakeOrigin(positionAfterPush:Long,count:Int):Long {
    require(count>0 && positionAfterPush>=count)
    return positionAfterPush-count
}
