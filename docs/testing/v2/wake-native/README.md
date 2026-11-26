# Fixed packaged SherpaWake / ONNX native fixture probe

See design.md for architecture and explicit limitations. This is a new test-only port probe from
main9dd265e7; model/business/versions/defaults are unchanged. It is NOT WakeReaderTest's controlled
keyword or the six controlled host Sherpa cases. Existing WakeUploadTest only supplies the constructor
pattern; it lacks these isolation/hash/positive/cleanup guards and is not the selected method.

## Review / build / artifact

```
scripts/with-build-lock python3 app/src/androidTest/run-wake-probe-regression.py
python3 app/src/androidTest/check-wake-packaging.py
# Set ANDROID_HOME and ANDROID_SDK_ROOT to the same existing SDK first.
scripts/with-build-lock ./gradlew --offline --no-daemon --max-workers=1 -Pv2Test \
  -I app/src/androidTest/wake-model.init.gradle :app:assembleV2DebugAndroidTest
python3 app/src/androidTest/strip-probe-fixtures.py \
  app/build/outputs/apk/androidTest/v2Debug/app-v2Debug-androidTest.apk \
  <wake-unsigned.apk> --known-wake-fixtures
<SDK>/build-tools/35.0.0/zipalign -P 16 -f 4 <wake-unsigned.apk> <wake-aligned.apk>
<SDK>/build-tools/35.0.0/apksigner sign --ks <existing-debug-key> \
  --ks-key-alias androiddebugkey --out <wake-test.apk> <wake-aligned.apk>
```

The init script permits only that test task/-Pv2Test, and gives the final APK exactly one
NativeWakeModelRunner, target com.littlebuddy.sim.v2, no test Activity declaration. Ordinary build
without init remains SimUiRunner; the timestamp init/runner/3s/60s/diagnostic allowlists are untouched.
This APK is a separate native-model probe distribution: do NOT invoke the timestamp runner component
against it. Keep prior test APK hashes; root installs only reviewed same-signature test updates, not
a new business APK. Target must contain the same real SherpaWake/KeywordSpotter/AAR and five hash-matched
model assets (RC8 already has them); a test update never replaces target classes. Verify final APK
DEX class_defs do NOT define SherpaWake, WakeReader, KeywordSpotter, NativeReadLedger or other production
classes. The small WakeProbeEngine adapter delegates directly to target SherpaWake, without a test
keyword implementation in the selected production method. Host fake engines only test orchestration.

The explicit known-fixture mode validates scripts/wake-fixtures.sha256, keeps exactly its three
synthetic PCM entries and rejects any unknown asset/audio, wrong hash, missing or duplicate entry.
Original/default strip mode still removes all three and rejects unknown audio. resources.arsc and
native so are STORED/aligned; the tool copies source ZipInfo rather than mutating compression before
source decompression. Check retained payload SHA against raw AGP entries, final aapt runner, signature
and zipalign; a ZIP policy unit archive is not proof of installability or hardware execution.

## One invocation after QA/root review and real idle preflight

Use the existing native timestamp README's actual root-authorized idle/identity/device-reservation
procedure (including unknown/active/unsaved-draft refusal). A boolean flag/PID is NOT authority to kill
or displace business. Instrumentation can restart its target before Java preflight, so real host
preflight remains required. Do not silently stop a process, touch V1/credentials/lockscreen, grant
owner permission, or require user functional point tests. Root handles a known empty controlled test
residue only under the already documented explicit preparation authorization. The test itself never
force-stops anything. No RECORD_AUDIO grant is needed or requested: it never constructs AudioRecord.
Permission/focus/keyguard/interactive/isolation or busy shared lease remains a dependency, not success.

```
adb -s "$SERIAL" shell am instrument --no-logcat -w -r \
  -e class com.littlebuddy.NativeWakeModelTest#packagedProductionModelOnFrozenFixtures \
  -e nativeWakeModelProbe true -e businessIdlePreflight true -e knownWakeFixtures true \
  com.littlebuddy.sim.v2.test/com.littlebuddy.NativeWakeModelRunner
```

Exactly one method, three exact true flags, no URL/path/duration/audio overrides. Unknown argument
keys (including secondary class/file/listener/runner selectors) are rejected; only the required
class/three flags and disableAnalytics (forced true) are accepted. Missing flags or
class-wide/multiple selection are rejected; ordinary default-runner discovery returns dependency
before native model allocation. Runner substitutes plain Application and blank secure foreground V2
component instance; it never constructs the production Application/Activity, owner/Grant/PIN/import,
TTS/capture/transport/feedback runtime. This is not a business-auth bypass or evidence owner flow works.

Root observes once with a finite host timeout (e.g.90s for focus5s+worker65s+cleanup1.5s). No retry for
FAIL/skip/unknown. Host timeout or missing final status is not PASS. Worker uses fixed kernel wall60s,
process CPU45s and input229448 sample ceilings, one model at a time with production numThreads1.
It hashes all five target model files and all three known synthetic fixtures before constructing any
model. Each of silence32000, command-alone61464, wake56300 and gap-12079684 gets a fresh actual
SherpaWake stream. Silence/command consume the complete input and must have zero hit; positive cases
stop on first real hit (production's single-hit stream is not reset) and require raw 0<tail<=fed.
No clamp, synthetic hit injection, origin reset or threshold changes. The final budget guard also
runs on exceptional/cancel exit so a slow close cannot wash an observed overrun into a skip.

Cancellation clears test byte/short/hash scratch on the caller, sets the real production allowed
callback false, and attempts finite join. That callback checks budget between native decode calls;
no claim JNI can be interrupted or its private float/native copies erased while blocked. Close is
worker-only, after accept returns, never concurrent with decode; every returned engine is closed
in finally. A partial constructor or throwing close is unconfirmed and quarantines the process lease.
No second model starts until close returns. Real worker join AND native-not-allocated AND all model
close returns must complete before releasing the shared child/management recorder lease. No recorder
stop task exists; metadata says not_applicable rather than claiming real AudioRecord stop proof.
Unknown worker/native release, cleanup exception and typed invariant FAIL dominate clean dependency.
No arbitrary native exception message/body is emitted, only class/phase/fixed failure code.

## Accept only explicit combined oracle

One final status7 bundle wake_probe_phase=finished, wake_probe_outcome=PASS, JSON junit_failure=false,
JUnit OK1 AND hashes_verified=true; models_attempted/constructed/closed=4; worker_joined=true;
model_release_confirmed=true; owned_lease_complete=true; process_lease=released. Require four case
aggregates: silence/command hits0 with full fed samples, wake/gap hits1 with raw bounded tail and
actual supplied count. samples_offered must match aggregates and <=229448. Record verified fixture
and model SHA metadata, probe_elapsed_ms/process_total_cpu_ms, last_guard wall/CPU and fixed budgets.
Guard times are last successful budget observations, not a fabricated elapsed measurement for a stuck
JNI; outer elapsed is separately reported even on timeout. Preflight is recorded, never inferred
from a default value. If hashes were not all verified, SHA labels are expected_unverified instead
of presenting constants as actual observations. Only aggregate data, not PCM/content/recognition text.

Close proof means production stream.release/spotter.release returned and the worker actually joined,
not proof of physical zeroization of immutable/native storage. Confirm target process/audio state is
idle after instrumentation before any other reserved device work; unconfirmed worker keeps quarantine.
Keep all old production timestamp FAILs, earlier test install/guard FAILs and new fixture failures.
A successful single synthetic-fixture JNI run would prove only this fixed input/native model path on
that device/session. It does NOT prove microphone acoustics, real child speech, Capture startup/ring
continuity, first-word replay, voice-owner routes, complete wake flow or 60-minute full V2 acceptance.
Author never executes device/cloud/ASR/recording/playback or changes business APK/config/version.

After true worker join, last_case_id/offered/hits/raw_tail also retain the latest case observation
BEFORE its assertions (including out-of-bounds/negative-case hits); do not hide a bad raw tail by
only reporting completed cases. last_phase is the last operation, not a fabricated original failure
site after finally/close; fixed reason plus last-case metadata identify failed assertions.
