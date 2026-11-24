package com.littlebuddy.v2

/** Recorder-owned absolute sample ring. Returned copies survive delayed owner
 * dispatch and are emitted once; KWS timestamps have an explicit capture origin.
 */
internal class WakeSamples(private val capacity: Int = 16000) {
    private val ring = ShortArray(capacity)
    var position = 0L; private set
    private var cursor = 0L
    fun push(samples: ShortArray, count: Int) {
        require(count in 1..samples.size && count <= capacity)
        for (i in 0 until count) ring[((position + i) % capacity).toInt()] = samples[i]
        position += count
    }
    fun begin(keywordTail: Long, preRoll: Int = 2560) {
        require(keywordTail in 0..position)
        cursor = maxOf(0, keywordTail - preRoll, position - capacity)
    }
    fun inspectAfter(keywordTail: Long, observe: (ShortArray) -> Unit) {
        var start = maxOf(keywordTail, position - capacity)
        while (start < position) {
            val size = minOf(320L, position - start).toInt()
            observe(ShortArray(size) { ring[((start + it) % capacity).toInt()] })
            start += size
        }
    }
    fun onset() { cursor = maxOf(cursor, position - capacity) }
    fun read(): List<ShortArray> {
        check(cursor >= position - capacity)
        val result = mutableListOf<ShortArray>()
        while (cursor < position) {
            val size = minOf(320L, position - cursor).toInt()
            result += ShortArray(size) { ring[((cursor + it) % capacity).toInt()] }
            cursor += size
        }
        return result
    }
    fun follow(preRoll: Int = 2560) { cursor = maxOf(0, position - preRoll) }
    fun clear() { ring.fill(0); cursor = position }
}
