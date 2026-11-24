package com.littlebuddy.v2
/** Aggregate-only instrumentation opt-in; no PCM retained, at most 512 one-second records. */
internal class SyntheticCaptureMeter {
 private var samples=0L;private var count=0;private var power=0.0;private var nonzero=0;private var peak=0;private var records=0
 fun accept(frame:ShortArray,size:Int):String? {
  if(records>=512)return null
  for(i in 0 until size){val v=frame[i].toInt();power+=v.toDouble()*v;if(v!=0)nonzero++;peak=maxOf(peak,kotlin.math.abs(v))}
  samples+=size;count+=size
  if(count<16000)return null
  val result="PCM end=$samples count=$count rms=${kotlin.math.sqrt(power/count).toInt()} nonzero=$nonzero peak=$peak"
  count=0;power=0.0;nonzero=0;peak=0;records++;return result
 }
}
