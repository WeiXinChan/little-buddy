package com.littlebuddy.v2.feedback

import java.security.SecureRandom
import java.util.UUID

/** RFC9562 5.7: original creation epoch milliseconds; never remint an existing material key. */
internal object FeedbackKeys {
    private val random=SecureRandom()
    fun create(created: Long): String {
        if(created !in 0..0xffffffffffffL)throw FeedbackFailure(Failure.CLOCK)
        return UUID((created shl 16) or 0x7000L or (random.nextInt(4096).toLong()),
            (random.nextLong() and 0x3fffffffffffffffL) or Long.MIN_VALUE).toString()
    }
    fun checked(value: String, submission: Boolean=false): UUID {
        val id=try { UUID.fromString(value) } catch(_:Exception) { throw FeedbackFailure(Failure.INVALID) }
        if(id.toString()!=value || id.variant()!=2 || (if(submission)id.version()!=7 else id.version() !in setOf(4,7)))
            throw FeedbackFailure(Failure.INVALID)
        return id
    }
}
