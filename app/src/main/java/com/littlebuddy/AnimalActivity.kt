package com.littlebuddy

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.PI
import kotlin.math.sin

internal enum class AnimalEvent {
    REPLY_END, FINAL_ACK, SEGMENT_CONFIRMATION, TURN_COMMIT, PLAYBACK_RELEASE,
    WAKE_COMMAND, ASR_READY, PCM_SEGMENT, PCM_BUFFERED,
    WAKE_CAPTURE, WAKE_CAPTURE_RELEASED, WAKE_PROMPT, WAKE_PROMPT_RELEASED, OPEN_SOCKET,
    CAPTURE_FRAME, ASR_UPLOAD_END, PCM_HEAD_ADVANCED, TONE, TONE_DISPATCH, TAIL_TIMER, IMAGE_TIMER, CAPTURE_DISPATCH, IMAGE_SHOWN,
}

/** Debug instrumentation can pause delivery at the same boundaries used by the real adapters. */
internal interface AnimalProbe {
    fun deliver(event: AnimalEvent, action: () -> Unit)
    fun observe(event: AnimalEvent)
    fun wakeInput(): ((ShortArray, Int) -> Unit)? = null
    val syntheticCapture: Boolean get() = false
}

open class AnimalActivity : Activity() {
    private val product get() = this is BuddyActivity
    private var face: BuddyFace? = null
    private var connection: BuddyConnection? = null
    private var restartPending = false
    private var wakeCapture = false
    private var wakeCaptureId: Long? = null
    private var wakePromptId: Long? = null
    private var wakePrompt = false
    private var wakeEntry = false
    private var focusHeld = false
    private var wakePermissionAsked = false
    private val screenOff = object : android.content.BroadcastReceiver() {
        override fun onReceive(context: android.content.Context, intent: android.content.Intent) {
            if (intent.action == android.content.Intent.ACTION_SCREEN_OFF) reset()
        }
    }
    internal var probe: AnimalProbe? = null

    private fun deliver(event: AnimalEvent, action: () -> Unit) {
        val inspector = probe
        if (inspector == null) action() else inspector.deliver(event, action)
    }

    private data class Segment(val text: String, val image: Int?)
    private data class Receipt(val action: String, val permit: String, val completed: Int, val mode: String)
    private class Reply(val key: JSONObject, val segments: List<Segment>) {
        val streams = mutableListOf<CloudPcm>()
        var played = 0
        var confirmed = 0
        var ended = false
        var receipt: Receipt? = null
        var scheduled = false
        var claimed = false
    }

    private val handler = Handler(Looper.getMainLooper())
    private val client = OkHttpClient.Builder().pingInterval(java.time.Duration.ofSeconds(3))
        .retryOnConnectionFailure(false).followRedirects(false).followSslRedirects(false).build()
    private val cloudMode by lazy { product || intent.getBooleanExtra("privateGame", false) }
    @Volatile private var upload: AnimalUpload? = null
    private var speech = false
    private var captureSealed = false
    private var captureReleased = false
    private var cloudReady = false
    private var uploadBlockedSince: Long? = null
    private val uploadPump = Runnable { drainUpload() }
    private var endpointField: EditText? = null
    private var tokenField: EditText? = null
    private lateinit var audio: AndroidAudio
    private val manager by lazy { getSystemService(AudioManager::class.java) }
    private val focus by lazy {
        AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE)
            .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).build())
            .setOnAudioFocusChangeListener({ if (it < 0 && focusHeld) reset("音频焦点丢失，请重新开始") }, handler)
            .build()
    }
    private var socket: WebSocket? = null
    private var resumed = false
    private var permissionPending = false
    private var launchPending = false
    private var startAfterPermission = false
    private var generation = 0L
    private var sequence = 0L
    private var slot: Long? = null
    private var slotGeneration = 0L
    private var cloudPlayback: Long? = null
    private var capturing = false
    private var frames = false
    private var answer: JSONObject? = null
    private var reply: Reply? = null
    private var deadline: Runnable? = null
    private lateinit var status: TextView
    private lateinit var caption: TextView
    private lateinit var count: TextView
    private lateinit var picture: ImageView
    private var buddy: Button? = null
    private lateinit var start: Button
    private lateinit var stop: Button
    private var input: EditText? = null
    private lateinit var sendAnswer: Button
    private var silence: Button? = null
    private var fault: Button? = null
    private var permutations: CheckBox? = null
    private var suppressRevealReceipt: CheckBox? = null

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        launchPending = !product && state == null && intent.getBooleanExtra("startGame", false)
        if (product) createProduct() else createDebug()
        audio = AndroidAudio(handler, frame = { id, detected, endpoint ->
            deliver(AnimalEvent.CAPTURE_FRAME) {
                val synthetic = upload?.synthetic == true
                captureFrame(id, detected && !synthetic, endpoint && !synthetic)
            }
        }, failed = { id ->
            if (id == slot && slotGeneration == generation) reset("音频失败，请重新开始")
        }, played = ::played, released = { id ->
            val current = reply
            if (cloudPlayback == id) traceCloud("release_notice", id)
            if (cloudPlayback == id || (!capturing && current != null && current.played == current.segments.size)) {
                deliver(AnimalEvent.PLAYBACK_RELEASE) {
                    if (cloudPlayback == id) {
                        traceCloud("release_applied", id)
                        cloudPlayback = null
                    }
                    released(id)
                }
            } else {
                released(id)
            }
        }, diagnostics = null, pcm = if (cloudMode) { id, samples, size ->
            val current = upload
            if (current?.operation == id && !current.synthetic && !current.frame(samples, size)) {
                handler.post { if (upload === current) reset("语音上传超出限制，请重新开始") }
            }
        } else null)
        if (product) registerReceiver(screenOff, android.content.IntentFilter(android.content.Intent.ACTION_SCREEN_OFF))
        render()
    }

    private fun createProduct() {
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val configuration = BuddySetup(this)
        val screen = BuddyScreen(this, ::startProduct, ::resetToWake, ::sealCloud)
        face = screen.face
        status = screen.status
        count = screen.count
        caption = screen.caption
        picture = screen.picture
        start = screen.start
        stop = screen.stop
        sendAnswer = screen.finish
        connection = configuration.load()
        if (connection == null) {
            val secure = android.view.WindowManager.LayoutParams.FLAG_SECURE
            window.addFlags(secure)
            setContentView(configuration.form { config ->
                connection = config
                setContentView(screen.root)
                window.clearFlags(secure)
                prepareWake()
            })
        } else {
            setContentView(screen.root)
        }
    }

    private fun startProduct() {
        if (!resumed) return
        if (socket != null || wakeCapture || wakePrompt) reset()
        if (slot != null) {
            restartPending = true
            render("稍等一下", BuddyMood.WAITING)
        } else {
            requestStart()
        }
    }

    private fun prepareWake() {
        if (!product || !resumed || connection == null || permissionPending) return
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            if (slot != null && slotGeneration != generation) rearmAfterRelease = true
            else armWake()
        } else if (!wakePermissionAsked) {
            wakePermissionAsked = true
            permissionPending = true
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 2)
        }
    }

    private fun armWake(afterPrompt: Boolean = false) {
        if (!product || connection == null || !eligible() || slot != null ||
            socket != null || probe?.syntheticCapture == true) return
        if (!holdFocus()) return
        val id = occupy()
        val epoch = generation
        val pending = AnimalUpload(id, null, synthetic = false)
        upload = pending
        wakeCapture = true
        wakeCaptureId = id
        wakeEntry = false
        captureSealed = false
        captureReleased = false
        speech = false
        cloudReady = false
        probe?.observe(AnimalEvent.WAKE_CAPTURE)
        audio.captureWake(id, probe?.wakeInput()) {
            val keyword = if (afterPrompt) null else try {
                SherpaWake(assets)
            } catch (error: LinkageError) {
                throw IllegalStateException("Wake model unavailable", error)
            }
            WakeReader(keyword, command = {
                handler.post {
                    deliver(AnimalEvent.WAKE_COMMAND) {
                        if (upload === pending && epoch == generation && eligible()) {
                            wakeEntry = true
                            speech = true
                            capturing = true
                            frames = true
                            connect()
                        }
                    }
                }
            }, solo = {
                handler.post {
                    if (upload === pending && epoch == generation && eligible()) wakePrompt = true
                }
            }, frame = { samples, count ->
                val accepted = pending.frame(samples, count)
                if (!accepted) handler.post {
                    if (upload === pending) reset("语音上传超出限制，请重新开始")
                }
                accepted
            })
        }
        if (afterPrompt) {
            render("正在听", BuddyMood.LISTENING)
            timeout(12_000, ::resetToWake)
        } else render()
    }

    private var rearmAfterRelease = false

    private fun playWakePrompt() {
        val bytes = assets.open("wake/prompt.pcm").use { it.readBytes() }
        val buffer = java.nio.ByteBuffer.wrap(bytes).order(java.nio.ByteOrder.LITTLE_ENDIAN)
        val samples = ShortArray(bytes.size / 2) { buffer.short }
        render("我在听", BuddyMood.SPEAKING)
        probe?.observe(AnimalEvent.WAKE_PROMPT)
        val id = occupy()
        wakePromptId = id
        audio.play(id, samples)
        timeout(3_000) { reset("播放超时，请重新开始") }
    }

    private fun holdFocus(): Boolean {
        if (focusHeld) return true
        focusHeld = manager.requestAudioFocus(focus) == AudioManager.AUDIOFOCUS_REQUEST_GRANTED
        if (!focusHeld) render("音频暂不可用，请重新开始", BuddyMood.ERROR)
        return focusHeld
    }

    private fun createDebug() {
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(32, 24, 32, 24)
        }
        fun label(value: String) = TextView(this).apply {
            text = value
            textSize = 20f
            layout.addView(this)
        }
        fun button(value: String, action: () -> Unit) = Button(this).apply {
            text = value
            setOnClickListener { action() }
            layout.addView(this)
        }
        label(if (cloudMode) "瓦力 · 私有猜动物" else "瓦力 · 猜动物模拟")
        if (!cloudMode) label("假转写由按钮提交。麦克风仅在本机检测声音。回复用字幕和提示音，无 ASR、LLM 或语音合成。")
        if (cloudMode) {
            fun field(hintText: String, type: Int) = EditText(this).apply {
                hint = hintText
                inputType = InputType.TYPE_CLASS_TEXT or type or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
                isSingleLine = true
                isSaveEnabled = false
                importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
                layout.addView(this, LinearLayout.LayoutParams(-1, -2))
            }
            label("有效语音会送往私有服务。看到「正在听」后再说话。")
            endpointField = field("私有 WSS 地址", InputType.TYPE_TEXT_VARIATION_URI)
            endpointField?.setText("wss://127.0.0.1:8444/v1/animal")
            tokenField = field("游戏设备令牌", InputType.TYPE_TEXT_VARIATION_PASSWORD)
        }
        buddy = button("摸摸瓦力") {
            buddy?.text = "瓦力眯眼笑"
            val epoch = generation
            handler.postDelayed({ if (epoch == generation) buddy?.text = "摸摸瓦力" }, 500)
        }
        status = label("点按开始猜动物").apply {
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        count = label("完成 0 / 3")
        caption = label("")
        picture = ImageView(this).apply {
            contentDescription = "揭晓示意图"
            visibility = View.GONE
            layout.addView(this, LinearLayout.LayoutParams(180, 180))
        }
        start = button("开始猜动物", ::requestStart)
        stop = button("停止") { reset() }
        input = EditText(this).apply {
            hint = "模拟回答，例如「告诉我答案」"
            isSingleLine = true
            isSaveEnabled = false
            importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
            layout.addView(this, LinearLayout.LayoutParams(-1, -2))
        }
        sendAnswer = button(if (cloudMode) "结束说话" else "结束录音并提交模拟回答") {
            if (cloudMode) sealCloud() else seal(input?.text.toString())
        }
        silence = button("注入静默") { seal(null) }
        fault = button("注入断线") { reset("模拟服务断开，请重新开始") }
        permutations = CheckBox(this).apply {
            text = "末 ACK 先到并重复回执"
            layout.addView(this)
        }
        suppressRevealReceipt = CheckBox(this).apply {
            text = "故障注入：扣留揭晓段确认"
            layout.addView(this)
        }
        if (cloudMode) {
            listOfNotNull(input, silence, fault, permutations, suppressRevealReceipt).forEach { it.visibility = View.GONE }
        }
        setContentView(ScrollView(this).apply { addView(layout) })
    }

    private fun captureFrame(id: Long, detected: Boolean, endpoint: Boolean) {
        if (id != slot || slotGeneration != generation || !capturing || answer != null || (cloudMode && captureSealed)) return
        if (!frames) {
            frames = true
            render(if (cloudMode) "正在听" else "正在听 · 等待模拟输入", BuddyMood.LISTENING)
            timeout(12_000) { if (cloudMode) sealCloud() else seal(null) }
        }
        if (cloudMode) {
            if (detected && !speech) {
                val current = checkNotNull(reply)
                speech = true
                val start = event("turn.start", current).put("listen_id", checkNotNull(current.receipt).permit)
                if (upload?.start(start) != true) {
                    reset("语音连接已断开，请重新开始")
                    return
                }
                timeout(18_000) { sealCloud() }
            }
            if (endpoint) sealCloud()
        } else if (endpoint && !input?.text.isNullOrBlank()) seal(input?.text.toString())
    }

    // Instrumentation can send a fixed in-memory PCM frame to the fake provider.
    internal fun injectSyntheticCapture() {
        check(cloudMode && probe?.syntheticCapture == true && frames)
        val operation = checkNotNull(slot)
        val pending = checkNotNull(upload)
        check(pending.frame(ShortArray(320), 320))
        captureFrame(operation, detected = true, endpoint = true)
    }

    private fun traceCloud(event: String, operation: Long, segment: Int = 0) {
        android.util.Log.i("AnimalTiming", "event=$event op=$operation segment=$segment ms=" +
            android.os.SystemClock.elapsedRealtime())
    }

    private fun played(id: Long) {
        val current = reply ?: return
        if (id != slot || slotGeneration != generation || capturing || wakeCapture || wakePrompt) return
        if (product) render("稍等一下", BuddyMood.WAITING)
        val number = ++current.played
        if (cloudMode) {
            traceCloud("segment_drained", id, number)
            current.streams[number - 1].abort()
        }
        val acknowledge = {
            if (current === reply) {
                if (send(event("playback.segment_completed", current).put("number", number)) && cloudMode) {
                    traceCloud("segment_ack", id, number)
                }
            }
            Unit
        }
        if (number == current.segments.size) deliver(AnimalEvent.FINAL_ACK, acknowledge)
        else acknowledge()
    }

    override fun onResume() {
        super.onResume()
        resumed = true
        if (launchPending || startAfterPermission) {
            launchPending = false
            startAfterPermission = false
            requestStart()
        }
        prepareWake()
        render()
    }

    override fun onPause() {
        resumed = false
        reset()
        super.onPause()
    }

    override fun onDestroy() {
        if (product) unregisterReceiver(screenOff)
        audio.close()
        handler.removeCallbacksAndMessages(null)
        client.dispatcher.executorService.shutdown()
        super.onDestroy()
    }

    private fun eligible() = resumed && checkSelfPermission(Manifest.permission.RECORD_AUDIO) ==
        PackageManager.PERMISSION_GRANTED && getSystemService(android.os.PowerManager::class.java).isInteractive &&
        !getSystemService(android.app.KeyguardManager::class.java).isKeyguardLocked

    private fun requestStart() {
        if (!resumed || socket != null || slot != null || permissionPending) return
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            permissionPending = true
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1)
            return
        }
        if (eligible()) connect()
    }

    override fun onRequestPermissionsResult(code: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(code, permissions, results)
        if (code == 2) {
            permissionPending = false
            prepareWake()
            render()
        } else if (code == 1) {
            permissionPending = false
            if (results.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
                if (resumed) requestStart() else startAfterPermission = true
            } else {
                render("请允许麦克风权限", BuddyMood.ERROR)
            }
        }
    }

    private fun connect() {
        val request = Request.Builder()
        if (cloudMode) {
            val config = if (product) connection else BuddyConnection.parse(
                endpointField?.text.toString().trim(), tokenField?.text.toString(),
            )?.takeIf { it.url.host in setOf("127.0.0.1", "localhost") && it.url.port != 8443 }
            if (config == null) {
                render(if (product) "设备尚未配置" else "请检查私有 WSS 地址和游戏设备令牌", BuddyMood.ERROR)
                return
            }
            request.url(config.url).header("Authorization", "Bearer ${config.token}")
        } else request.url("ws://127.0.0.1:8765/animal")
        if (!holdFocus()) return
        val regression = permutations?.isChecked == true
        probe?.observe(AnimalEvent.OPEN_SOCKET)
        socket = client.newWebSocket(request.build(),
            object : WebSocketListener() {
                private var stream: CloudPcm? = null
                private var segmentKey: JSONObject? = null
                private var segmentNumber = 0
                private var wireReplyKey: JSONObject? = null
                private var wireSegments = 0
                private var wireSegmentIndex = 0
                private var discardSegment = false

                private fun protocolFailure(webSocket: WebSocket) =
                    dispatch(webSocket) { reset("游戏协议错误，请重新开始") }

                override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                    if (discardSegment) return
                    try {
                        checkNotNull(stream).push(bytes.toByteArray())
                    } catch (_: Exception) {
                        protocolFailure(webSocket)
                    }
                }

                override fun onOpen(webSocket: WebSocket, response: okhttp3.Response) = dispatch(webSocket) {
                    val start = JSONObject().put("event", "session.start").put("v", 1)
                        .put("catalog", "animal-click-1").put("images", JSONArray(images.keys.toList()))
                    if (product) start.put("conversation", true)
                    if (wakeEntry) start.put("wake", true)
                    if (!product) start.put("ack_first", regression).put("duplicate", regression)
                        .put("hold_reveal", suppressRevealReceipt?.isChecked == true)
                    send(start)
                }
                override fun onMessage(webSocket: WebSocket, text: String) {
                    val message = try {
                        JSONObject(text)
                    } catch (_: org.json.JSONException) {
                        protocolFailure(webSocket)
                        return
                    }
                    val kind = message.optString("event")
                    if (cloudMode) {
                        try {
                            when (kind) {
                                "reply" -> {
                                    val key = message.getJSONObject("key")
                                    val previous = wireReplyKey
                                    if (previous != null && (key.getString("session_id") != previous.getString("session_id") ||
                                            key.getInt("turn_id") <= previous.getInt("turn_id"))) return
                                    check(stream == null && !discardSegment)
                                    wireSegments = message.getJSONArray("segments").length()
                                    check(wireSegments in (if (product) 0 else 1)..8)
                                    wireSegmentIndex = 0
                                    wireReplyKey = key
                                }
                                "segment.start" -> {
                                    check(stream == null && !discardSegment)
                                    val key = message.getJSONObject("key")
                                    val latest = checkNotNull(wireReplyKey)
                                    if (key.getString("session_id") != latest.getString("session_id") ||
                                        key.getInt("turn_id") < latest.getInt("turn_id")) {
                                        discardSegment = true
                                        return
                                    }
                                    check(key.getInt("turn_id") == latest.getInt("turn_id"))
                                    val number = message.getInt("number")
                                    check(number == wireSegmentIndex + 1 && number <= wireSegments)
                                    wireSegmentIndex = number
                                    val incoming = CloudPcm({ name, operation ->
                                        android.util.Log.i("AnimalTiming", "event=$name op=$operation ms=" +
                                            android.os.SystemClock.elapsedRealtime())
                                        if (name == "playback_head_first_advance") dispatch(webSocket) {
                                            if (slot == operation && slotGeneration == generation) {
                                                if (product && !capturing && cloudPlayback == operation) {
                                                    render("正在说话", BuddyMood.SPEAKING)
                                                }
                                                probe?.observe(AnimalEvent.PCM_HEAD_ADVANCED)
                                            }
                                        }
                                    }, bufferEntireSegment = true)
                                    stream = incoming
                                    segmentKey = key
                                    segmentNumber = number
                                    handler.post {
                                        if (webSocket !== socket) incoming.abort()
                                        else deliver(AnimalEvent.PCM_SEGMENT) {
                                            if (webSocket === socket && eligible()) acceptStream(message, incoming)
                                            else incoming.abort()
                                        }
                                    }
                                    return
                                }
                                "segment.end" -> {
                                    if (discardSegment) {
                                        discardSegment = false
                                        return
                                    }
                                    val key = message.getJSONObject("key")
                                    check(message.getInt("number") == segmentNumber &&
                                        key.getString("session_id") == segmentKey?.getString("session_id") &&
                                        key.getInt("turn_id") == segmentKey?.getInt("turn_id"))
                                    checkNotNull(stream).seal(message.getInt("samples"))
                                    stream = null
                                    dispatch(webSocket) { probe?.observe(AnimalEvent.PCM_BUFFERED) }
                                    return
                                }
                            }
                        } catch (_: Exception) {
                            protocolFailure(webSocket)
                            return
                        }
                    }
                    dispatch(webSocket) {
                        val event = when (kind) {
                            "reply.end" -> AnimalEvent.REPLY_END
                            "playback.segment_committed" -> AnimalEvent.SEGMENT_CONFIRMATION
                            "turn.committed" -> AnimalEvent.TURN_COMMIT
                            "turn.ready" -> AnimalEvent.ASR_READY
                            else -> null
                        }
                        val receiveCurrent = {
                            if (webSocket === socket) receiveSafely(message)
                        }
                        if (event == null) receiveCurrent() else deliver(event, receiveCurrent)
                    }
                }
                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) =
                    dispatch(webSocket) {
                        // The terminal receipt can be queued just before a normal close.
                        if (code != 1000 || reply?.receipt?.action != "end") reset("游戏服务已断开")
                    }
                override fun onFailure(webSocket: WebSocket, t: Throwable, response: okhttp3.Response?) =
                    dispatch(webSocket) { reset(if (product) "连不上了，请再试一次" else "连接失败，请检查服务和 USB 转发") }
            })
        render("正在连接游戏服务", BuddyMood.WAITING)
        timeout(if (cloudMode) 12_000 else 5_000) { reset("连接或回复超时，请重新开始") }
    }

    private fun dispatch(source: WebSocket, action: () -> Unit) {
        handler.post { if (source === socket) action() }
    }

    private fun receiveSafely(message: JSONObject) {
        try {
            receive(message)
        } catch (_: org.json.JSONException) {
            reset("模拟协议错误，请重新开始")
        } catch (_: IllegalArgumentException) {
            reset("模拟题库或协议不匹配")
        }
    }

    private fun receive(message: JSONObject) {
        if (!eligible()) {
            reset("音频条件变化，请重新开始")
            return
        }
        val key = message.getJSONObject("key")
        val current = reply
        if (message.getString("event") == "reply") {
            val next = key.getInt("turn_id")
            if (current == null) {
                require(next == 1)
            } else if (!current.claimed || key.getString("session_id") != current.key.getString("session_id") ||
                next != current.key.getInt("turn_id") + 1) {
                return
            }
            require(slot == null || wakeEntry && current == null)
            val segments = message.getJSONArray("segments")
            require(segments.length() in (if (product) 0 else 1)..8)
            if (wakeEntry && current == null) require(segments.length() == 0)
            reply = Reply(key, List(segments.length()) { index ->
                val item = segments.getJSONObject(index)
                Segment(if (cloudMode) "" else item.getString("text"), if (item.isNull("image_id")) null else
                    requireNotNull(images[item.getString("image_id")]))
            })
            picture.visibility = View.GONE
            if (cloudMode) timeout(8_000) { reset("等待语音段超时") }
            else playNext(checkNotNull(reply))
            return
        }
        if (cloudMode && message.getString("event") == "turn.ready") {
            if (current != null && matches(key, current) && speech && !cloudReady) {
                if (upload?.ready() != true) {
                    reset("语音上传失败，请重新开始")
                    return
                }
                cloudReady = true
                uploadBlockedSince = null
                drainUpload()
            }
            return
        }
        if (current == null || key.getString("session_id") != current.key.getString("session_id") ||
            key.getInt("turn_id") != current.key.getInt("turn_id") || current.claimed) return
        when (message.getString("event")) {
            "reply.end" -> current.ended = message.getInt("count") == current.segments.size
            "playback.segment_committed" -> {
                val number = message.getInt("number")
                if (number == current.confirmed + 1 && number <= current.played) {
                    current.confirmed = number
                    if (cloudMode) traceCloud("segment_confirmed", slot ?: 0L, number)
                    current.segments[number - 1].image?.let {
                        picture.setImageResource(it)
                        picture.visibility = View.VISIBLE
                        probe?.observe(AnimalEvent.IMAGE_SHOWN)
                    }
                }
            }
            "turn.committed" -> if (message.getInt("count") == current.segments.size && current.receipt == null) {
                val action = message.getString("next_action")
                val mode = message.optString("mode", "game")
                require(mode == "chat" || mode == "game")
                require(current.segments.isNotEmpty() || action == "end")
                current.receipt = Receipt(action, message.optString("listen_id"), message.getInt("completed"), mode)
            }
        }
        proceed(current)
    }

    private fun matches(key: JSONObject, current: Reply) =
        key.optString("session_id") == current.key.optString("session_id") &&
            key.optInt("turn_id") == current.key.optInt("turn_id")

    private fun acceptStream(message: JSONObject, incoming: CloudPcm) {
        val current = reply
        val key = message.optJSONObject("key")
        if (current != null && key != null && !matches(key, current)) {
            incoming.abort()
            return
        }
        if (current == null || key == null || current.claimed ||
            message.optInt("number") != current.streams.size + 1 || current.streams.size >= current.segments.size) {
            incoming.abort()
            reset("语音段顺序错误，请重新开始")
            return
        }
        current.streams.add(incoming)
        if (slot == null && current.played == current.streams.lastIndex) playNext(current)
    }

    private fun playNext(current: Reply) {
        if (cloudMode) {
            val stream = current.streams.getOrNull(current.played)
            if (stream == null) {
                timeout(8_000) { reset("等待语音段超时") }
                return
            }
            capturing = false
            render(if (product) "稍等一下" else "正在播放回复", BuddyMood.WAITING)
            timeout(18_000) { reset("播放或回执超时，请重新开始") }
            val operation = occupy()
            cloudPlayback = operation
            audio.playStream(operation, stream)
            return
        }
        caption.text = current.segments[current.played].text
        capturing = false
        render("正在播放模拟提示音")
        timeout(8_000) { reset("播放或回执超时，请重新开始") }
        val samples = ShortArray(30_000) { index ->
            val envelope = minOf(index, 29_999 - index, 480) / 480.0
            (sin(2 * PI * 440 * index / 24_000) * envelope * 1800).toInt().toShort()
        }
        deliver(AnimalEvent.TONE) {
            if (current === reply && slot == null) {
                audio.play(occupy(), samples)
                probe?.observe(AnimalEvent.TONE_DISPATCH)
            }
        }
    }

    private fun occupy(): Long {
        check(slot == null)
        return (++sequence).also {
            slot = it
            slotGeneration = generation
        }
    }

    private fun released(id: Long) {
        if (slot != id) return
        if (wakeCaptureId == id) {
            wakeCaptureId = null
            probe?.observe(AnimalEvent.WAKE_CAPTURE_RELEASED)
        }
        if (wakePromptId == id) {
            wakePromptId = null
            probe?.observe(AnimalEvent.WAKE_PROMPT_RELEASED)
        }
        slot = null
        if (slotGeneration != generation) {
            val restart = restartPending
            restartPending = false
            render()
            if (restart) requestStart()
            if (rearmAfterRelease) {
                rearmAfterRelease = false
                armWake()
            }
            return
        }
        if (wakeCapture) {
            wakeCapture = false
            if (wakePrompt) {
                upload?.close()
                upload = null
                playWakePrompt()
            } else if (wakeEntry) {
                captureReleased = true
                captureSealed = true
                capturing = false
                finishCloudCapture()
                reply?.let(::proceed)
            } else reset()
            return
        }
        if (wakePrompt) {
            wakePrompt = false
            deadline?.let(handler::removeCallbacks)
            armWake(afterPrompt = true)
            return
        }
        val current = reply ?: return
        if (capturing) {
            capturing = false
            if (cloudMode) {
                captureReleased = true
                finishCloudCapture()
                return
            }
            val pending = answer ?: return
            answer = null
            if (send(pending)) timeout(5_000) { reset("假服务等待超时") }
        } else if (current.played < current.segments.size) {
            playNext(current)
        } else {
            render("正在等待播放回执", BuddyMood.WAITING)
            proceed(current)
        }
    }

    private fun proceed(current: Reply) {
        val receipt = current.receipt ?: return
        val firstWakeReply = wakeEntry && current.key.getInt("turn_id") == 1
        if ((!firstWakeReply && slot != null) || !current.ended || current.confirmed != current.segments.size || current.scheduled) return
        current.scheduled = true
        count.visibility = if (receipt.mode == "chat") View.GONE else View.VISIBLE
        count.text = "完成 ${receipt.completed} / 3"
        val delay = if (receipt.action == "advance") 1100L else 250L
        val advance = {
            completeAction(current, receipt)
        }
        val timer = if (receipt.action == "advance") AnimalEvent.IMAGE_TIMER else AnimalEvent.TAIL_TIMER
        if (probe == null) handler.postDelayed(advance, delay) else deliver(timer, advance)
    }

    private fun completeAction(current: Reply, receipt: Receipt) {
        if (current !== reply || current.claimed) return
        if (wakeEntry && current.key.getInt("turn_id") == 1) {
            if (!eligible() || receipt.action != "listen" || receipt.mode != "chat") {
                reset("唤醒会话不可用，请重新开始")
                return
            }
            current.claimed = true
            val start = event("turn.start", current).put("listen_id", receipt.permit)
            if (upload?.start(start, socket) != true) reset("语音连接已断开，请重新开始")
            else timeout(18_000) { reset("等待语音回复超时") }
            return
        }
        if (!eligible() || slot != null) {
            reset("音频条件变化，请重新开始")
            return
        }
        current.claimed = true
        when (receipt.action) {
            "listen" -> {
                capturing = true
                frames = false
                val operation = occupy()
                if (cloudMode) {
                    speech = false
                    captureSealed = false
                    captureReleased = false
                    cloudReady = false
                    upload = AnimalUpload(operation, checkNotNull(socket), probe?.syntheticCapture == true)
                }
                audio.capture(operation)
                probe?.observe(AnimalEvent.CAPTURE_DISPATCH)
                render("正在打开麦克风", BuddyMood.WAITING)
                timeout(3_000) { reset("麦克风没有返回采集帧") }
            }
            "advance" -> {
                picture.visibility = View.GONE
                if (send(event("turn.advance", current))) timeout(if (cloudMode) 12_000 else 5_000) { reset("等待下一题超时") }
            }
            "end" -> if (product) resetToWake() else reset("本局已结束", keepCaption = true)
            else -> reset("模拟协议错误")
        }
    }


    private fun sealCloud() {
        val id = slot ?: return
        if (!capturing || !frames || captureSealed) return
        captureSealed = true
        if (speech) android.util.Log.i("AnimalTiming", "event=capture_sealed op=$id ms=" +
            android.os.SystemClock.elapsedRealtime())
        audio.stop(id)
        render("正在等待回复", BuddyMood.WAITING)
        timeout(5_000) { reset("麦克风清理或语音服务超时") }
    }

    private fun drainUpload() {
        handler.removeCallbacks(uploadPump)
        val pending = upload ?: return
        if (!cloudReady) return
        if (!eligible()) {
            reset()
            return
        }
        val result = pending.drain(captureSealed && captureReleased)
        if (result == AnimalUpload.Drain.BLOCKED) {
            val now = android.os.SystemClock.elapsedRealtime()
            val since = uploadBlockedSince ?: now.also { uploadBlockedSince = it }
            if (now - since >= 2_000) {
                reset("语音上传拥塞，请重新开始")
                return
            }
        } else uploadBlockedSince = null
        when (result) {
            AnimalUpload.Drain.FAILED -> reset("语音上传失败，请重新开始")
            AnimalUpload.Drain.ENDED -> {
                pending.close()
                upload = null
                probe?.observe(AnimalEvent.ASR_UPLOAD_END)
                timeout(12_000) { reset("等待语音回复超时") }
            }
            else -> handler.postDelayed(uploadPump, if (result == AnimalUpload.Drain.MORE) 1 else 20)
        }
    }

    private fun finishCloudCapture() {
        if (!captureSealed || !captureReleased || upload == null) return
        if (speech) {
            drainUpload()
            return
        }
        val current = checkNotNull(reply)
        upload?.close()
        upload = null
        if (send(event("listen.silence", current).put("listen_id", checkNotNull(current.receipt).permit))) {
            timeout(12_000) { reset("等待语音回复超时") }
        }
    }

    private fun seal(text: String?) {
        val current = reply ?: return
        val id = slot ?: return
        if (!capturing || !frames || answer != null) return
        answer = event(if (text == null) "listen.silence" else "turn.start", current)
            .put("listen_id", checkNotNull(current.receipt).permit)
        if (text != null) answer?.put("text", text.take(80))
        input?.text?.clear()
        audio.stop(id)
        render("正在等待模拟回复")
        timeout(4_000) { reset("麦克风清理超时") }
    }

    private fun event(name: String, current: Reply) = JSONObject().put("event", name).put("key", current.key)

    private fun send(event: JSONObject): Boolean {
        if (socket?.send(event.toString()) == true) return true
        reset("假服务已断开，请重新开始")
        return false
    }

    private fun timeout(ms: Long, action: () -> Unit) {
        deadline?.let(handler::removeCallbacks)
        deadline = Runnable(action).also { handler.postDelayed(it, ms) }
    }

    private fun resetToWake() {
        reset()
        prepareWake()
    }

    private fun reset(message: String = "点按开始猜动物", keepCaption: Boolean = false) {
        generation++
        restartPending = false
        rearmAfterRelease = false
        wakeCapture = false
        wakeEntry = false
        wakePrompt = false
        handler.removeCallbacks(uploadPump)
        upload?.close()
        face?.clearTouch()
        deadline?.let(handler::removeCallbacks)
        deadline = null
        val previous = socket
        socket = null
        previous?.cancel()
        if (focusHeld) manager.abandonAudioFocusRequest(focus)
        focusHeld = false
        slot?.let(audio::stop)
        capturing = false
        frames = false
        answer = null
        upload = null
        reply?.streams?.forEach(CloudPcm::abort)
        reply = null
        picture.visibility = View.GONE
        count.visibility = View.VISIBLE
        count.text = "完成 0 / 3"
        if (!keepCaption) caption.text = ""
        input?.text?.clear()
        buddy?.text = "摸摸瓦力"
        render(if (product && message == "点按开始猜动物") "准备好了" else message,
            if (message == "点按开始猜动物" || keepCaption) BuddyMood.IDLE else BuddyMood.ERROR)
    }

    private fun render(message: String? = null, mood: BuddyMood? = null) {
        if (message != null) status.text = message
        mood?.let { face?.mood = it }
        val active = socket != null
        start.isEnabled = resumed && !permissionPending &&
            (if (product) !restartPending && (active || wakeCapture || wakePrompt || slot == null) else !active && slot == null)
        stop.isEnabled = active || restartPending || wakeCapture || wakePrompt
        sendAnswer.isEnabled = active && capturing && frames && answer == null
        if (cloudMode) {
            sendAnswer.isEnabled = active && capturing && frames && !captureSealed
            endpointField?.isEnabled = !active
            tokenField?.isEnabled = !active
        }
        silence?.isEnabled = sendAnswer.isEnabled
        fault?.isEnabled = active
        permutations?.isEnabled = !active && slot == null
        suppressRevealReceipt?.isEnabled = !active && slot == null
    }

    private companion object {
        val images = mapOf(
            "animal-dog" to R.drawable.animal_dog,
            "animal-cat" to R.drawable.animal_cat,
            "animal-duck" to R.drawable.animal_duck,
            "animal-rabbit" to R.drawable.animal_rabbit,
            "animal-elephant" to R.drawable.animal_elephant,
            "animal-giraffe" to R.drawable.animal_giraffe,
        )
    }
}
