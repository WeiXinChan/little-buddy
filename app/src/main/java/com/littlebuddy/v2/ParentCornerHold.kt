package com.littlebuddy.v2

/** Only a hold begun and retained inside the hidden parent corner can request verification. */
internal class ParentCornerHold {
    private var armed = false
    fun down(x: Float, y: Float, width: Int, height: Int): Boolean {
        armed = inside(x,y,width,height); return armed
    }
    fun move(x: Float, y: Float, width: Int, height: Int): Boolean {
        if (!inside(x,y,width,height)) armed=false
        return armed
    }
    fun cancel() { armed=false }
    fun fire(focused: Boolean): Boolean { val result=armed && focused; armed=false; return result }
    private fun inside(x:Float,y:Float,w:Int,h:Int)=w>0 && h>0 && x>=w*.90f && y>=h*.85f && x<=w && y<=h
}
