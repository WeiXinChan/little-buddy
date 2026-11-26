# Two-session startup diagnostic — test only, not a production fix

## Preserved real failure

OPPO PKW110/API36's first production-ledger probe really FAILED: business code20 hash78224c76…
and test3fbe0cdb… were installed and same-signed; foreground/RECORD_AUDIO true, locked false,
VOICE_COMMUNICATION 16k mono PCM16, min1280/nativeBytes6400/actual3200frames, start24ms.
29 timestamp calls returned-3; no first SUCCESS, no read; capture timestamp unavailable at startup.
All native/worker/stop/lease cleanup confirmed. That result is not a dependency skip, is not erased,
and must not be reclassified by this diagnostic. Original CLI attachments:
installed-check.json 01a21561-ea4d-7d23-b0ae-9dadf639ce76;
installed-probe-stdout.txt 01a21561-ec37-7537-b5ba-0b02f2df621d.

## What official sources do and do not establish

[AudioRecord API](https://developer.android.com/reference/android/media/AudioRecord#getTimestamp(android.media.AudioTimestamp,%20int))
allows unavailable/ERROR_INVALID_OPERATION and gives no180ms first-timestamp guarantee.
AOSP android16-release:

- [AudioRecord.cpp](https://android.googlesource.com/platform/frameworks/av/+/refs/heads/android16-release/media/libaudioclient/AudioRecord.cpp): start flushes, resets read counts and clears timestamps until a server push; read obtains/releases buffers and advances the client read count.
- [JNI bridge](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/core/jni/android_media_AudioRecord.cpp): reads ExtendedTimestamp, then asks for the best valid pair before filling Java fields.
- [AudioTimestamp.h](https://android.googlesource.com/platform/frameworks/av/+/refs/heads/android16-release/media/libaudioclient/include/media/AudioTimestamp.h): best-pair selection searches server/kernel, excluding client; absence yields INVALID_OPERATION.
- [Client proxy](https://android.googlesource.com/platform/frameworks/av/+/refs/heads/android16-release/include/private/media/AudioTrackShared.h) polls the shared timestamp queue.

This supports a readiness/publishing question, NOT a conclusion that positive read is a public API
precondition. AOSP is not OPPO's private HAL. One -3 window cannot prove permanent unsupported source.
The deterministic host counterexample is explicitly conditional: if publishing requires a read,
the unchanged production ready-before-read gate expires at180ms with read count0. Other controlled
models publish after250ms without reading or remain unavailable, showing why hardware data is needed.

## Minimal bounded experiment

One explicit instrumentation method requests at most TWO native sessions, no retries:

1. TIMESTAMP_ONLY: poll timestamp, never read.
2. READ_THEN_TIMESTAMP: immediately try NON_BLOCKING read, clear it, then poll timestamp.

Same fixed1000ms window and10ms interval, max128 API attempts/session, max19200 read samples in B
(1s nominal plus original3200 buffer), one320-sample temporary array; retained/uploaded audio0.
Use ONLY original VOICE_COMMUNICATION/16000/mono/PCM16/nativeBytes6400. If current minimum exceeds
6400 or actual buffer differs from3200, report dependency rather than enlarge/change source.
No PCM inspection/level/VAD, storage, playback, model, config, token, SSH or network sink.
The no-read control may overrun native storage by design; it measures availability only, not
continuity. Its raw counter/read difference is not admission to production. JNI delay is included
in observed elapsed time; an uninterruptible call may overrun the software window. External worker
join/cancel is bounded, failure/unknown release prevents session2; physical JNI interruption is not
promised. Every read is cleared immediately in finally, including read errors/cancellation.

Record API code histogram, first raw SUCCESS and first well-formed-pair time after start return,
also latency from start call, P/time, age, regressions, actual read/sample counts, termination limit,
native minimum/actual buffer/start duration and complete native/worker/stop/owned-lease proof.
Cleanup and stop failures still override dependencies using the already-reviewed shared decision.
Only advance to B after A's true release and worker join. No live business recorder is closed or
replaced. At most two sessions; selecting both old/new methods in one runner invocation is rejected.

Possible observations are not proof of production readiness:

|A/B|Interpretation|
|---|---|
|both yield a well-formed pair|both available within this window; >180ms is compatible with startup latency|
|only B yields a pair|read-path OR order/warm-up association; cannot establish causality with two sessions|
|only A yields a pair|session/route variability; preserve data|
|neither yields a pair|unavailable within TWO bounded windows, not permanently unsupported|
|invalid/regressing pair|timestamp quality anomaly, regardless of raw SUCCESS|

Fixed A-then-B order can warm hardware; changing time/source/config or adding a third retry is not
part of this experiment. JUnit OK1 means only diagnostic sessions cleaned up. Final scope is always
DIAGNOSTIC_ONLY_NOT_PRODUCTION_PASS and production_probe_pass=false, never the original PASS oracle.
Original nativeTimestampAndProductionLedger method and production Capture/NativeReadLedger/thresholds
are unchanged. Production bootstrap remains a separate decision requiring hardware evidence plus
bounded time/audio/cache, original sample coordinates, cancellation and explicit loss handling.

## Exact root execution after review (author executes no devices)

Reuse the reviewed host idle preparation in ../native-timestamp/README.md: device exclusivity,
matching installed business code20 hash/signature, no live session/audio/other test/unsaved input.
Known controlled empty test residue may be explicitly stopped by Mac per root authorization;
unknown/live business may not be killed. Do not ask users for recordings, point tests or key presses.
Update only same-package signed test APK; do not reinstall/alter business APK or change credentials.
Dedicated runner empty Application and target-component replacement foreground isolation remain.

```
adb -s "$SERIAL" install -r -t "$REVIEWED_TEST_APK"
adb -s "$SERIAL" shell am instrument -w -r \
 -e class com.littlebuddy.NativeTimestampStartupTest#compareTimestampStartup \
 -e nativeTimestampProbe true -e nativeTimestampStartupDiagnostic true \
 -e businessIdlePreflight true \
 com.littlebuddy.sim.v2.test/com.littlebuddy.NativeTimestampRunner
```

Capture only this instrumentation's metadata stdout. No full logcat/PCM/environment contents.
Use --no-logcat if supported as in the previous procedure. The allowlist contains exactly the old
production-probe method OR the new diagnostic method, with an additional explicit diagnostic flag.
Do not run the old production oracle and relabel its original failure, or interpret diagnostic OK
as a production fix. Root alone executes/reviews device observations and decides integration.

## Local checks

Same heavy.lock wrapper and existing SDK/cache. Host startup counterexamples + previous cleanup
priority regressions: app/src/androidTest/run-native-probe-regression.py. Device execution is pending.
Build only assembleV2DebugAndroidTest with -Pv2Test and explicit native-timestamp.init.gradle.
Retain final aapt runner/target checks, existing-key signature, PCM-free filtered artifact hash and
original known-failing APK/hash evidence. No version bump, production build-file change or APK freeze.
