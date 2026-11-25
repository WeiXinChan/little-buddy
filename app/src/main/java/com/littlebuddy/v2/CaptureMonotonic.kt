package com.littlebuddy.v2
/** Exact clock/timebase required by AudioTimestamp.TIMEBASE_MONOTONIC. */
internal object CaptureMonotonic { fun nowMs()=System.nanoTime()/1_000_000 }
