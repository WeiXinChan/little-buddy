package com.littlebuddy

import com.littlebuddy.voice.PcmStream

internal interface PcmOutput {
    val head: Int
    fun write(samples: ShortArray, offset: Int): Int
    fun start()
}

/** Drives a nonblocking output on the audio worker. */
internal fun pumpPcm(
    operation: AudioWorker.Operation,
    stream: PcmStream,
    threshold: Int,
    output: PcmOutput,
    now: () -> Long,
    waitForProgress: () -> Unit,
) {
    var chunk: ShortArray? = null
    var offset = 0
    var written = 0
    var padding = 0
    var started = false
    var lastProgress = now()
    var previousHead = 0

    while (!operation.cancelled) {
        check(!stream.aborted)
        val head = output.head
        if (head > previousHead) {
            lastProgress = now()
            if (previousHead == 0) stream.playbackHeadAdvanced(operation.id)
        }
        previousHead = head
        if (chunk == null) {
            chunk = stream.poll()
            offset = 0
        }
        val drained = chunk == null && stream.ended
        if (started && drained && head >= written) return

        // Native playback may need to refill its start buffer after an underrun.
        // Pad only a verified end, then stop at the last actual frame.
        val tailPadding = if (drained) (threshold - (written - head) - padding).coerceAtLeast(0) else 0
        val samples = chunk
        val accepted = if (samples != null) {
            output.write(samples, offset)
        } else if (tailPadding > 0) {
            output.write(ShortArray(tailPadding), 0)
        } else 0
        check(accepted >= 0)
        if (accepted > 0) {
            lastProgress = now()
            if (samples == null) padding += accepted else {
                written += accepted
                offset += accepted
                if (offset == samples.size) chunk = null
            }
        }
        if (!started && written + padding >= threshold) {
            check(!stream.aborted)
            if (!operation.commitStart()) return
            output.start()
            stream.playbackRequested(operation.id)
            started = true
        }

        // Short gaps drain naturally into silence. A stalled segment fails the turn.
        check(now() - lastProgress < 2_000L)
        if (accepted == 0) waitForProgress()
    }
}
