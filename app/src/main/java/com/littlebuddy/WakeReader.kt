package com.littlebuddy

import android.content.res.AssetManager
import com.k2fsa.sherpa.onnx.KeywordSpotter
import com.k2fsa.sherpa.onnx.KeywordSpotterConfig
import com.k2fsa.sherpa.onnx.OnlineModelConfig
import com.k2fsa.sherpa.onnx.OnlineTransducerModelConfig

internal interface WakeKeyword : AutoCloseable {
    /** Estimated exclusive keyword tail relative to the start of this capture. */
    fun accept(samples: ShortArray, count: Int): Long?
}

internal class SherpaWake(assets: AssetManager, private val keyword: String = "瓦力瓦力",
                          keywordFile: String = "wake/keywords.txt") : WakeKeyword {
    private val spotter: KeywordSpotter
    private val stream: com.k2fsa.sherpa.onnx.OnlineStream

    init {
        val suffix = "epoch-13-avg-2-chunk-16-left-64"
        spotter = KeywordSpotter(assets, KeywordSpotterConfig(
            modelConfig = OnlineModelConfig(
                transducer = OnlineTransducerModelConfig(
                    encoder = "wake/encoder-$suffix.int8.onnx",
                    decoder = "wake/decoder-$suffix.onnx",
                    joiner = "wake/joiner-$suffix.int8.onnx",
                ),
                tokens = "wake/tokens.txt",
                modelType = "zipformer2",
                numThreads = 1,
            ),
            keywordsFile = keywordFile,
        ))
        stream = spotter.createStream()
    }

    var detectedKeyword: String? = null; private set
    override fun accept(samples: ShortArray, count: Int): Long? {
        stream.acceptWaveform(FloatArray(count) { samples[it] / 32768f }, 16_000)
        while (spotter.isReady(stream)) {
            spotter.decode(stream)
            val result = spotter.getResult(stream)
            if (result.keyword.isNotEmpty() && (keyword == "*" || result.keyword == keyword)) {
                detectedKeyword = result.keyword
                val last = result.timestamps.lastOrNull() ?: error("Missing wake timestamp")
                return ((last + 0.12f) * 16_000).toLong()
            }
        }
        return null
    }

    override fun close() {
        stream.release()
        spotter.release()
    }
}

/** Runs on the recorder worker. The handoff replays each sample once, then follows the same reader. */
internal class WakeReader(
    private var keyword: WakeKeyword?,
    private val command: () -> Unit,
    private val solo: () -> Unit,
    private val frame: (ShortArray, Int) -> Boolean,
) : AutoCloseable {
    private val ring = ShortArray(48_000)
    private val detector = SpeechDetector(320, initialFloor = if (keyword != null) 36.0 else null)
    private val replay = ShortArray(320)
    private var head = 0L
    private var tail: Long? = if (keyword == null) 0 else null
    private var checked = 0L
    private var voiced = false
    private var handoff = false

    override fun close() {
        keyword?.close()
        keyword = null
        ring.fill(0)
        replay.fill(0)
    }

    fun accept(samples: ShortArray, count: Int): Boolean {
        if (handoff) {
            if (!frame(samples, count)) return false
            return detector.accept(samples, count) != SpeechDetector.Event.END
        }

        for (i in 0 until count) ring[((head + i) % ring.size).toInt()] = samples[i]
        head += count
        val engine = keyword
        if (engine != null) {
            tail = engine.accept(samples, count)?.coerceIn(maxOf(0, head - ring.size + 2560), head)
                ?: return true
            checked = checkNotNull(tail)
            keyword = null
            engine.close()
        }
        val boundary = checkNotNull(tail)
        val observationEnd = if (boundary == 0L) head else minOf(head, boundary + 8000)
        while (checked < observationEnd) {
            val size = copyFromRing(checked, replay, observationEnd)
            checked += size
            if (detector.accept(replay, size) == SpeechDetector.Event.SPEECH) voiced = true
        }
        if (voiced) {
            var cursor = maxOf(0, boundary - 2560, head - ring.size)
            // After the prompt, retain only the most recent half second of local listening.
            if (boundary == 0L) cursor = maxOf(cursor, head - 8000)
            while (cursor < head) {
                val size = copyFromRing(cursor, replay)
                if (!frame(replay, size)) return false
                cursor += size
            }
            handoff = true
            command()
        } else if (boundary > 0 && head >= boundary + 8000) {
            solo()
            return false
        }
        return true
    }

    private fun copyFromRing(start: Long, output: ShortArray, end: Long = head): Int {
        val size = minOf(output.size.toLong(), end - start).toInt()
        for (i in 0 until size) output[i] = ring[((start + i) % ring.size).toInt()]
        return size
    }
}
