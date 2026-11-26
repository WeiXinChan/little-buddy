# Bounded capture startup admission

The original OPPO production probe is a real FAIL: 29 unavailable (-3) timestamps, read0,
180ms timeout. Its stdout remains unchanged. The later PR80 two-session diagnostic found a first
pair at141ms from start call without reads, and170ms with reads, on the same source/format/buffer.
This does not prove read is a timestamp precondition. The no-read A counter/time sequence was NOT
healthy16k continuous capture. B still did not exercise the production ledger. Neither is a new
production PASS. Originals and intermediate failed local checks accompany the issue evidence.

## Admission algorithm and fixed bounds

Capture constructs NativeReadLedger and CaptureBootstrap immediately BEFORE startRecording. Both
MONOTONIC/BOOT origins therefore precede the earliest possible sample of this recording, including
any time inside startRecording. Original AudioRecord VOICE_COMMUNICATION/16k/mono/PCM16 and
max(minBytes,6400) allocation are unchanged; no buffer enlargement is used for this repair.

1. `beginStartup` opens a single finite admission phase: strictly less than500ms from that original
   clock origin, at most8000 successful read samples in one16000-byte private prefix, plus one
   320-sample scratch. This fits within the existing16000-sample/1s wake ring. Unavailable timestamps
   do not prevent NON_BLOCKING reads. Reads are FIFO, starting at original coordinate0. Every successful
   read advances the SAME cumulative ledger count; no timestamp/read/empty read rebases that count.
2. Before AND after reads, and after timestamp JNI returns, compute worst-case production
   `U=ceil((monoNow-monoOrigin+1ms)*16016/1000)` and unread `max(0,U-totalRead)`.
   Require `capacity-320-unread` and its remaining millisecond budget to be positive. All model-free
   startup IO/scheduling time accumulates in U. The +1ms is integer MONOTONIC rounding, not extra
   native storage. A short read does not renew a complete180ms room budget. Native/server stalls
   cannot hide overflow by returning a small later frame counter. A blocked read is charged before
   its returned count is credited, which can conservatively reject a healthy but unproven interval.
3. Each hardware candidate still passes all original future/age (<=100ms), regression, relabel,
   rate15984..16016Hz (+/-2 samples pair rounding), timebase and cumulative native room checks.
   Startup also requires counter <= U and earliest counter-derived sample0 time no earlier than the
   pre-start clock envelope. No arbitrary frame offset is subtracted. A zero-frame pair is not an
   admission anchor and is not used as a rate baseline; two POSITIVE, increasing counter pairs
   must establish the rate under the original check. Repeated identical pairs do not advance it.
4. Only then `finishStartup` checks the original sample0 BOOT bridge, closes the finite software
   startup budget permanently, and enables replay. No software time is accepted as a sample timestamp.
   Prefix samples are replayed once in FIFO order to the REAL Capture→SherpaWake path, using absolute
   cumulative coordinates/sampleTime(position), before fresh native reads. The ring/KWS coordinate
   is not reset to the first stamp. A later unknown/stale/rate/continuity failure still stops capture.
5. Before admission there is no KWS/VAD/upload consumer. Each read scratch is finally zeroed. The
   prefix is erased on consumed ranges, failure, finally and caller cancellation; its short cache
   monitor is never held across IO. Caller cancellation can erase staged PCM while worker JNI is
   blocked. JNI's own in-flight destination cannot be certified erased until it returns and its
   finally runs. Native stop/release, true worker/stop join, process lease, model disposal order and
   child/management exclusivity remain unchanged; unknown release remains quarantined.

500ms is a finite startup ceiling allowing delayed first pairs beyond the old180ms while bounding
retained PCM to half the existing wake ring. It is NOT a promise to wait500ms irrespective of native
room: a read/scheduling gap exhausting the original capacity fails earlier. If first pair arrives
at/beyond500ms, or a second trustworthy advancing pair cannot be obtained before then, fail closed.
Two hardware pairs alone do not prove the prefix has no loss: the pre-start cumulative U-minus-read
proof is mandatory for the ENTIRE unanchored interval. No first stamp can erase an earlier violation.

## Explicit assumptions and conservative failures

This proof uses AudioRecord's fresh, ordered read/counter coordinates since start (AOSP start flush
and counter reset references in ../timestamp-startup/README.md), and the SAME existing +/-1000ppm
rate envelope. The software upper bound exists ONLY during <=500ms; at1000ppm that uncertainty is
at most8 samples, accounted by MAX_RATE, not600s of accumulating clock drift. Long recordings use
hardware pairs exclusively. Vendor semantics/rate outside that contract must fail, not infer an
origin or silently drop samples. Hardware first-pair ages and latency are not themselves proof of
this contract; a matched production probe on OPPO remains required.

A startRecording call blocked300ms is now conservatively rejected even if the substitute starts
producing only near the end: without observations during the blocked call its full original buffer
cannot be proven safe. The former positive300ms-before-start substitute case is preserved in the
original evidence. The focused regression now tests short60ms startup as positive and300ms both
before/after actual native start as explicit rejection, with no upload. This is a documented stricter
admission rule, not tolerance expansion. Continuous short60ms KWS burst/catch-up and native timestamp
API delay80ms remain positive; sustained100ms-per-read cumulative backlog remains a real rejection.

## Production probe dependency and evidence boundaries

NativeTimestampTest now constructs the SAME pre-start NativeReadLedger/CaptureBootstrap as Capture,
then discards/zeros prefix rather than invoking a model. Its original >=3s continuous read and
>=100 positive reads/32000 samples checks and cleanup failure priority remain. No timestamp-age/rate
or release threshold was relaxed. Late API returns are included in admission budget, never hidden.

**This test references target APP production classes. An updated test APK with old business code20
cannot execute the new algorithm.** Root must first review this PR, freeze/build/install a matching
new business APK and test APK from the same final source, verify identities/signatures, and only then
execute `NativeTimestampTest#nativeTimestampAndProductionLedger` using the reviewed dedicated runner
and `--no-logcat`. This turn only compiles Kotlin main+androidTest. No version change, APK freeze,
installation, cloud call, Mac contact or additional agent dispatch is performed.

Offline `scripts/with-build-lock python3 scripts/test-v2-capture.py` exercises actual Capture with
controlled recorder/owner, actual ledger/bootstrap, and actual SherpaWake source with controlled
ONNX ports. It checks delayed250ms anchoring, absent/late/stale/regressing/rate-invalid stamps,
original sample0/keyword coordinates, private-cache clearing/cancellation, no unanchored accept/upload,
21/50frame owner delay, lease/native cancellation and accumulating continuous native loss. This is
code and controlled continuity evidence; it is not a real ONNX acoustic run or OPPO production PASS.

## Probe caller cancellation integration

ProbeControl now registers the actual prefix through ProbeStartupCancellation BEFORE native start.
Its foreground/focus callback, timeout, outer-finally and worker release all synchronously clear the
same staged cache before stop/native IO. Registration racing an already-cancelled caller also clears
immediately. The helper delegates to actual CaptureBootstrap.clear; it does not hold a monitor across
JNI. Two controlled regressions block a real bootstrap read after filling the prefix, cancel/late-
register from the caller, and require all staged samples zero while the worker remains blocked. After
unblocking, the read scratch must also be finally zero and admission must remain rejected. Existing
stop/cleanup failure-over-dependency priority is exercised alongside them (15 host methods total).
