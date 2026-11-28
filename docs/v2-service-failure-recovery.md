# V2 SERVER_VOICE recovery (code35 draft)

This change does not establish the cause of the original provider failure or count recovery as an effective answer/P12 success. Code34's clarification clip remains unchanged. The separately supervised, root-generated service-failure cue is pinned below; no placeholder asset or candidate APK is supplied by this draft.

## Authority and lifecycle

Only the current VoiceClient socket with fixed classified VOICE, current epoch/revision, and the authenticated session/turn identity can authorize an episode. The authenticated identity survives input revision advancement, but advancing does not authorize a different session/turn. Close/interrupt clears that identity. Unknown/quota/auth/safety/timeout/protocol/clock/native-release failures do not authorize recovery.

`ACTIVE -> trusted VOICE -> HOLD/retire -> confirmed release -> LOCAL_WAKE -> real KWS wake -> CONNECTING -> IMPORTING -> ACTIVE_NEW`.

Retirement requires native stop/release, KWS/model release, worker join, independent stop-task completion and ProcessRecorders lease completion. Capture.close uses one total 500ms join budget for worker and stop task; missing proof quarantines. No socket exists in LOCAL_WAKE. A typed RecoveryWakeGrant restores RuntimeRetryGate only after successful import; it never retries the previous request or restores its context.

Management, background, lost focus and lock revoke the current generation, PCM and connection. A still-eligible episode may obtain a new local-only generation after a genuine foreground return and full admission/release checks. Its cue-used flag survives this transition. A non-whitelisted or release failure blocks the episode. Successful promotion allows ordinary lifecycle behavior again.

## Capture ownership and bounds

CaptureSessionPort changes only Capture's endpoint. Recorder, ledger/bootstrap, absolute KWS coordinates, VAD, original ring and recorder lease remain the existing implementation. No V1/shared Sherpa/native model or clock/rate/phase/freshness limit changes.

The worker establishes the real WakeBoundary before posting the owner callback. Only then may RecoveryHandoff own PCM copied by the existing WakeSamples reader. It never retains the original scratch frame. Accepted and rejected batches transfer ownership; rejected/cancelled/consumed arrays are zeroed. The normal CaptureUploads ring is bypassed while pending, then reused unchanged after import.

Independent limits (the first reached wins):

- Handoff queued plus in-flight PCM <=48000 samples; <=512 FIFO rows including quiet markers.
- Each retained frame's earliest sample BOOT age <3000ms, including its own duration.
- Authenticated compatible READY strictly before original wake BOOT+2500ms.
- Original wake/lastSpeech BOOT and 15000ms admission/deadline remain in force.

Consequently a one-second pre-wake prefix can exhaust the oldest-sample bound before the full 2500ms connect allowance. The limits are caps, not promises of successful connection latency. Pending PCM is volatile, not an offline utterance queue. Every failure clears it; there is one connection attempt per true wake.

READY calls wake with the original coordinates, then imports a bounded FIFO in four-frame owner turns. Live captures append behind that FIFO. Endpoint tick (solo/probe/seal) remains inhibited until empty, while permission/cancellation and original response-deadline checks continue. No lock spans a consumer/native call. Client send admission also observes handoff cancellation. The transition to LIVE occurs on the same owner before the next endpoint tick.

## One playback owner

OutputSlot serializes normal Playback and SERVICE_CUE Track leases. A retired route/callback/lease cannot touch the newer native Track. Cleanup failures poison the slot. The service cue uses existing Playback's nonblocking local writes and inherited volume/speed, a distinct ticket and fixed diagnostics, never normal ACK/effectivePlayed/context. Speech/KWS/lifecycle/management cancels it; native cleanup must complete before acquiring a new lease. The cue is once per failure episode and not replayed on resume.

## Evidence and remaining gates

Host Capture tests execute production Capture/ledger/bootstrap/lease against controlled AudioRecord/KWS platform ports; they are not actual ONNX/JNI or device evidence. The TLS driver compiles actual VoiceClient/Playback/Capture and uses controlled native/VAD/KWS ports, transient test TLS credentials and zero providers. It checks the real retirement, next wake, bounded import, first native head/reply and stale/slow rejection path.

Before a code35 APK: independent review, final source freeze, adequate disk headroom and one canonical same-signer private build. Fixed asset verification/inventory and version metadata are prepared. No installation or deployment is authorized to the author. Existing canonical APKs/evidence/toolchains must remain intact. Current filesystem headroom is insufficient for an unplanned native merge/strip plus APK/signing peak; no APK build has started.

## Collector association (not a global scope exemption)

At authenticated READY, `RUNTIME_RECOVERY_BIND` uses the physical Capture's original `(activity,transport,capture)` scope, and `current_transport/current_capture` identify the new client transport and the SAME physical capture. `episode/generation` bind the one handoff; `wake_boot_ms/wake_frame/read_frame` retain the original boundary. New client phase scope remains `(activity,new_transport,0)`, where capture0 is the existing legitimate client convention. There is no second CAPTURE_START. The physical lease still ends only at its matching CAPTURE_RELEASE/WORKER_JOINED.

Kotlin-shaped positive: physical `Scope(1,2,7)` START; current episode/generation1/2 accepts real wake frame640 at BOOT100000; authenticated new client `Scope(1,3,0)` READY; one RECOVERY_BIND scope(1,2,7), current_transport3/current_capture7, episode1/generation2, wake_frame640/read_frame960/wake_boot_ms100000; its normal audio/head may associate ONLY through this explicit edge while the physical lease remains active. Negative: equal/older target transport, retired generation, duplicate binding, different activity/capture, missing active physical START or already released lease must not lend association to an old callback. RecoveryEpisode tests cover the source-side duplicate/retired/equal-target refusal; collector lifecycle checks are root's separate script responsibility.

Root-generated service cue is now included unmodified: SHA256 `9da6b3f7011d6a2c70fbe21ebb301d5487b0c7633cf7bf210938335cc9cc17eb`, 164160bytes/82080samples/3.42s, 24kHz mono S16LE. Source/release validation pins actual bytes, not a self-reported digest. Version metadata is35/recovery1; this remains a source draft, not an installed or built code35 artifact.


The deadline observer race is explicit: both the capture worker and VoiceClient permission/pump may observe handoff expiry first. Admission now records the first fixed rejection/BOOT and zeroes ownership synchronously before returning false; subsequent cancellation preserves that evidence. Deterministic tests exercise both observation orders at exactly2500ms. The real TLS slow case requires one original trusted VOICE callback, old release, one next wake/connection, no READY/import/head, CONNECT_DEADLINE at original wake+2500ms or later, zero retained samples and final recorder lease release. A lifecycle terminal on the new client may follow this refusal; it cannot replace the original VOICE or the recorded budget rejection. Historical WIP failure logs remain retained separately.
