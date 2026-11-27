package com.littlebuddy.v2

/** Native result times are seconds: patched decoder timestamps share the original stream origin, never delivery time.
 * Retains the existing estimated exclusive-tail offset (.12f), rounding conservatively down. */
internal object KeywordTail {
    fun sample(startSeconds:Double,lastSeconds:Double,fed:Long):Long {
        require(startSeconds.isFinite() && lastSeconds.isFinite() && startSeconds==0.0 && lastSeconds>=0 && fed>0)
        val samples=(startSeconds+lastSeconds+0.12f.toDouble())*16000.0
        require(samples.isFinite() && samples>=1 && samples<Long.MAX_VALUE.toDouble())
        val tail=kotlin.math.floor(samples).toLong()
        check(tail in 1..fed) {"keyword coordinate outside submitted samples"}
        return tail
    }
}
