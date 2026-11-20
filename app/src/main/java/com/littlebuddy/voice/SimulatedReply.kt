package com.littlebuddy.voice

import kotlin.math.PI
import kotlin.math.sin

// Local deterministic response. Audio output is a generated tone at 24 kHz.
class SimulatedReply(
    private val clock: Deadline,
    private val segment: (Turn, Segment) -> Unit,
    private val end: (Turn, Int) -> Unit,
) : ReplyPort {
    private var active: Turn? = null

    override fun request(turn: Turn) {
        active = turn
        clock.after(250) {
            if (active == turn) {
                val tone = ShortArray(4_800) { i ->
                    (sin(2 * PI * 440 * i / 24_000) * 2_000).toInt().toShort()
                }
                segment(turn, Segment(1, tone))
                if (active == turn) {
                    active = null
                    end(turn, 1)
                }
            }
        }
    }

    override fun cancel(turn: Turn) {
        if (active == turn) active = null
    }
}
