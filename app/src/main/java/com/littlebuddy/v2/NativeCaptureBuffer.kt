package com.littlebuddy.v2

/** Physical storage backing the existing startup contract, never invented ledger room.
 * 501ms worst-case production + original reserve + one full ms of positive room, chunk rounded.
 * The fixed result follows ceil((8025+320+17)/320)*320 =8640 frames /17280bytes.
 */
internal object NativeCaptureBuffer {
    const val MAX_BYTES=32000
    const val UPLOAD_MAX_AGE_MS=1200L // Original6400-byte profile; larger native storage cannot renew PCM age.
    fun requestedBytes(minimumBytes:Int):Int {
        require(minimumBytes in 1..MAX_BYTES)
        val produced=((NativeReadLedger.STARTUP_LIMIT_MS+1)*NativeReadLedger.MAX_RATE+999)/1000
        val room=(NativeReadLedger.MAX_RATE+999)/1000
        val frames=((produced+NativeReadLedger.RESERVE_FRAMES+room+319)/320)*320
        val bytes=maxOf(frames*2,((minimumBytes+1)/2)*2L)
        check(bytes<=MAX_BYTES)
        return bytes.toInt()
    }
    fun verifiedFrames(requestedBytes:Int,actualFrames:Int):Int {
        require(requestedBytes in 6400..MAX_BYTES && requestedBytes%2==0)
        require(actualFrames>NativeReadLedger.RESERVE_FRAMES) // OEM may round allocation up; never credit beyond request.
        return minOf(requestedBytes/2,actualFrames)
    }
}
