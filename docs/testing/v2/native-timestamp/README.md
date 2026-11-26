# Native timestamp driver probe (not executed on device by author)

Base main33af6923. Only androidTest and this procedure change. Main/v2Debug, frozen code20rc6,
production NativeReadLedger and every threshold remain byte-for-byte unchanged.

## Explicit test-only isolation

Build explicitly with the test-only init script below and select
`com.littlebuddy.NativeTimestampRunner`, not the default SimUiRunner. AGP rewrites source test manifest
instrumentation: the earlier source node became SimUiRunner, so that node was removed. This build
has ONE dedicated runner selected through androidComponents.finalizeDsl; ordinary builds without
this explicit init script still have SimUiRunner. The production build file and target APK are unchanged. This runner substitutes a plain
Application via newApplication (no FeedbackApplication startup), and only substitutes the existing
target component com.littlebuddy.V2VoiceActivity via newActivity with a test-only blank foreground
Activity. The replacement instance runs in the target component's UID/process; it is not an Activity
declared under the separate test APK UID. SDK compilation/manifest checks cannot prove it gains
real foreground focus on OPPO; that remains a mandatory runtime check/dependency.

No business V2VoiceActivity constructor, TTS/KWS/VAD model, parent runtime, credential loader,
VoiceClient, feedback runtime or network API is invoked. The probe is an explicitly authorized native
recorder-port instrumentation test with OS RECORD_AUDIO; it does not obtain/validate a ParentDomain
Grant, does not open a management page, and cannot establish that production owner/PIN flows pass.
The test-only runner is not packaged in the application APK and exposes no production auth bypass.

Acquire the real ProcessRecorders lease BEFORE changing focus/launching the test foreground.
If a child or management recorder already owns it, report NOT_RUN_DEPENDENCY without closing,
pausing or replacing that recorder. An already configured target is never used to fetch credentials.
Host-side idle preflight is REQUIRED: normal `am instrument` can restart a target process before
Java test preflight. Unknown/active business, recording/playback, another test, or unsaved parent
input must not be killed or displaced. A cached PID is not automatically an indefinite blocker:
root explicitly authorizes preparation of a known controlled empty test process, as below.
`--no-restart` is not a shortcut: AOSP instruments an existing process rather than constructing this
isolated Application; our Application identity check refuses a non-isolated application.
See [AOSP instrumentation implementation](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android15-release/services/core/java/com/android/server/am/ActivityManagerService.java).

## Exact invocation for root AFTER source review, on the one reserved device

Install only the matching-signed test APK alongside root's already-installed code20 candidate.
Do not replace the frozen target APK with a local app build. The Mac device owner first reserves
the one device and records METADATA: exact installed code20 APK hash/version, target PID, which
controlled test/install created it, secure=false/unconfigured state, no recording/playback/other
test, and no unsaved parent input. Do not read credentials or collect any input contents to prove
that state. Unknown state or any active business/draft remains DEPENDENCY; do not kill it.

For the root-confirmed controlled upgrade/install flow stopped at the uninitialized parent page:
first exit the page/application normally through the existing authorized automation, with no user
key presses. If the remaining PID is confirmed to be solely that empty test residue (all facts
above recorded), root has authorized Mac to explicitly stop ONLY that idle V2 package before
instrumentation. It must not touch V1, stored config/credentials, or lockscreen. Do not wait for OS
random cache eviction. A bare PID or businessIdlePreflight=true is not authority/identity; the
recorded prior state and root authorization are the condition. Instrumentation never silently
stops an unknown/active PID; the test itself performs no package stop command.

RECORD_AUDIO may use root's existing authorized test-permission preparation. The test never grants
permissions/unlocks screens itself. If permissions, focus, screen state or isolation fail, retain
the metadata and DEPENDENCY, not a driver pass or a user functional point-test request.

```sh
# SERIAL and TEST_APK selected by root. No device commands executed by author.
adb -s "$SERIAL" shell pidof com.littlebuddy.sim.v2
# Classify/record prior state first. Unknown/active/draft -> STOP this direction.
# Normal exit first. ONLY if confirmed root-authorized empty test residue remains:
# adb -s "$SERIAL" shell am force-stop com.littlebuddy.sim.v2
# The commented stop is a deliberate Mac action, never an automatic PID-based fallback.
adb -s "$SERIAL" install -r -t "$TEST_APK"
adb -s "$SERIAL" shell pidof com.littlebuddy.sim.v2
# Require empty before instrument; root keeps single-device ownership and prevents other launches.
adb -s "$SERIAL" shell am instrument --no-logcat -w -r \
  -e class com.littlebuddy.NativeTimestampTest#nativeTimestampAndProductionLedger \
  -e nativeTimestampProbe true -e businessIdlePreflight true \
  com.littlebuddy.sim.v2.test/com.littlebuddy.NativeTimestampRunner
```

Save this selected instrumentation stdout as METADATA ONLY. Do not collect full logcat, PCM,
recordings, transcripts or environmental content. Use `--no-logcat` as above. A missing option in
`am help` is not proof the parser rejects it: OPPO API36 accepted this option in a check against a
nonexistent component (no real probe started). AOSP Android16 [Am.java](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/cmds/am/src/com/android/commands/am/Am.java)
recognizes the option. If a different device actually rejects it, retain that response: root may
explicitly authorize plain `-w -r` text output with no protobuf/file/profile flags. In AOSP
[Instrument.java](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/cmds/am/src/com/android/commands/am/Instrument.java),
only ProtoStatusReporter calls readLogcat; TextStatusReporter emits the selected result bundles.
Do not invoke logcat or enable protobuf/file/profile reporting. Unknown vendor behavior remains
unverified. Never invoke the default runner or interpret a dependency skip as a driver pass.
Runner forces disableAnalytics=true.

An install observation timeout is not a terminal package-manager result. Retain the original
client/session handle and partial stdout/stderr, inspect that same package's active/historical
session and confirmation UI, and keep the device reserved while an owned install is live. Do not
submit another install merely because an observation expired. A new attempt requires proof the
original task is terminal or missing plus explicit bounded retry scope; preserve the first result.
A nonexistent-component parser check, an install attempt and a real probe invocation are separate
counts. None is hardware acceptance without the final probe oracle below.

Class/method is exactly the command above. Missing exact class/probe/host-idle arguments refuses
execution. Default-runner discovery reports an explicit dependency skip before native allocation.
The idle argument attests the root's host preflight only, not owner identity or capture permission.

## Measurements and oracle

Source: VOICE_COMMUNICATION, 16000Hz mono PCM16; nativeBytes=max(actual minimum,6400), reject
minimum outside1..32000. Record actual bufferFrames and validate it is >=requested and actual
format matches. Use real AudioTimestamp MONOTONIC and unmodified NativeReadLedger with exact
CaptureMonotonic and elapsedRealtime clocks. No software timestamp/provider substitute is used.

Require at least3000ms continuous successful ledger operation after first accepted timestamp,
at least100 positive reads /32000 samples. Emit only aggregate metadata every roughly1s and
on exit: first API success/first ledger acceptance latency, API status/count/max duration,
min/max stamp age, last native frame/time/delta, read/sample counts, remaining-room min/current,
permission/focus/lock status and actual native stop/release/worker/stop-task/lease confirmations.
This is more than one getTimestamp success; any production threshold failure is a FAIL, not
retuned or retried. A silenced recorder (where exposed by platform), missing permission/foreground,
locked screen, busy lease or legal native startup restriction is NOT_RUN_DEPENDENCY.

No PCM is persisted, sent to a socket/model, logged, summarized as content/amplitude, or copied
into result bundles. One320-sample read array is cleared in every read finally and outer finally.
All error paths attempt native stop/release; actual STOPPED and STATE_UNINITIALIZED must confirm.
Hold process lease until native release and true worker join; stop tasks are separately joined.
A blocked JNI/cleanup cannot be forcibly interrupted/proven released: mark FAIL/resource unknown,
keep lease failclosed, do not start another capture. Root must confirm instrumentation target process
ended before any further device work; no automatic business force-stop is part of this probe.

Accept only final status-code7 Bundle `v2_timestamp_phase=finished`, `v2_timestamp_outcome=PASS`,
real stopped/released/worker_joined/stop_task_joined true, lease released, continuous counts above,
AND JUnit OK1. Progress NOT_EXECUTED, failure or dependency skips are never hardware success.
Counterexample metadata retains the exact body-free production ledger reason. Native exceptions
are identified by class/phase/API/read status, not arbitrary message/body/logcat. If no native API
success, age sentinel Long.MIN/MAX means not observed. This does not prove acoustics/ASR/child speech,
network/SSH, owner/PIN/Grant, or production conversation/lifecycle integration.

## Local preparation

Use existing SDK/cache, no dependency installs:

    bash scripts/with-build-lock env ANDROID_HOME=<SDK> ANDROID_SDK_ROOT=<same> ./gradlew --offline --no-daemon --max-workers=1 -Pv2Test -I app/src/androidTest/native-timestamp.init.gradle :app:assembleV2DebugAndroidTest

Inspect the final APK using aapt dump xmltree: exactly one instrumentation named NativeTimestampRunner,
targetPackage com.littlebuddy.sim.v2, and no test APK Activity declaration. Keep the earlier ordinary
merged manifest (only SimUiRunner) as evidence that the default is unchanged. Do not infer runner
availability from the source XML or compilation alone. Inspect/sign/hash
app/build/outputs/apk/androidTest/v2Debug/app-v2Debug-androidTest.apk. Report exact source SHA/tree,
artifact hash/signature/runner and build result. Building the test APK does not mean OPPO execution.

### Exception priority regression and privacy-safe artifact

The real stop thread calls shared guardedProbeStop; native stop exceptions cannot escape to
Android's uncaught handler, and only exception class/category is retained. Worker cleanup errors
are separately retained even when the original failure is a dependency. Shared decideProbeResult
and enforce() drive BOTH final JSON/Bundle and the actual JUnit outcome: cleanup/stop errors or any
unconfirmed owned native/worker/stop/lease proof always throw safe AssertionError, never assumption
skip. Original dependency_reason is retained separately. Only a fully cleaned dependency may skip.
Host regression invokes that same enforce(), verifies actual thrown types/no uncaught message and
parses7 failure-priority JSON records (4 JUnit methods). No native hardware is faked into PASS.

    bash scripts/with-build-lock python3 app/src/androidTest/run-native-probe-regression.py

Standard AGP test APK contains three pre-existing wake PCM fixture inputs, unrelated to this probe.
They must NOT be distributed as probe output. The delivered probe-only test APK removes only those
unused assets and old signing records, preserves every remaining entry (including DEX/manifest)
byte-for-byte, then zipaligns and signs with the existing test key. Raw AGP APK is kept local only.
The exact filter is app/src/androidTest/strip-probe-fixtures.py; signatures/hashes and retained-entry
checks are in delivery evidence. This changes only the test artifact, never root's target APK or
production inventory. Other fixture-dependent test cases are not supported in this filtered APK;
only the explicitly selected native probe and its existing runner contract are the deliverable.

    python3 app/src/androidTest/strip-probe-fixtures.py <raw-test.apk> <unsigned-probe.apk>
    <sdk>/build-tools/35.0.0/zipalign -f 4 <unsigned-probe.apk> <aligned-probe.apk>
    <sdk>/build-tools/35.0.0/apksigner sign --ks <existing-debug-keystore> --ks-key-alias androiddebugkey --out <probe.apk> <aligned-probe.apk>

Require final JSON junit_failure=false, owned_lease_complete=true plus all cleanup flags for PASS;
any FAIL JSON must correspond to real JUnit FAIL even if dependency_reason is also populated.

## Fixed 60-second opt-in production-ledger observation (RC8 follow-up)

The existing `nativeTimestampAndProductionLedger` remains the default 3-second method. The new
`nativeTimestampAndProductionLedger60Seconds` shares its real CaptureBootstrap/NativeReadLedger,
AudioRecord source/format/native buffer, 500us phase model, long-rate/age/clock bridge/continuity
checks, process lease, foreground cancellation, sanitized result policy and native/worker/stop
release proof. Only instrumentation sources and this procedure change; no app version or production
code changes. It must run alongside a target APK built with these production classes (RC8 code22
already contains them); replacing the test APK never replaces classes loaded from the target.

After the original bounded startup (500ms/8000 samples), a single fixed 60000ms **continuous
observation** window starts. Startup and bounded cleanup are separate from that window; this is
not a promise that the entire instrumentation command returns within 60 seconds. No arbitrary
host duration, loop count or retry is supported. Before each timestamp/read API, a fresh elapsed
clock checks the deadline. An API returning at/after the deadline fails explicitly; a call cannot
be physically interrupted by Java. Reaching the deadline between API calls ends observation and
starts cleanup; no API is started at/after it. API blocking/worker timeout is never PASS.
The outer worker join is fixed at 67000ms (includes startup/native construction/cleanup), then
requests stop and joins worker/stop tasks for the original 1500ms limits. An unconfirmed worker,
stop task, native release or lease remains FAIL/failclosed; never start a second session.

The window also caps raw continuous samples at 968000 (60.5s of nominal 16k samples; conservative
finite instrumentation ceiling including initial native backlog, not a replacement for the much
stricter unchanged production ledger). PASS additionally needs at least 944000 continuous accepted
samples and 2900 positive continuous reads, the full window reached, all original checks and all
release proofs. No restart resets the cumulative ledger origin or budgets. Results distinguish
`continuous_raw_samples` (read return counts, including an eventual rejected tail) from accepted
`continuous_samples` and `samples_read` (production ledger total including startup). Sample arrays
are cleared immediately after each continuous read, as well as in all finally paths. Startup
prefix cancellation/clearing remains the production path. Only aggregate metadata is emitted;
no trace, PCM file, amplitude/content analysis, KWS, uploads or network operations.

Root must first perform and record the **same actual idle preflight described above**, reserve the
single device and verify exact target/test identity/signature. Unknown/active business is still a
dependency, not permission to force-stop. Use the dedicated runner and **all three flags**, exactly
one method and exactly one invocation after QA approval (author does not execute this):

```sh
adb -s "$SERIAL" shell am instrument --no-logcat -w -r \
  -e class com.littlebuddy.NativeTimestampTest#nativeTimestampAndProductionLedger60Seconds \
  -e nativeTimestampProbe true -e businessIdlePreflight true \
  -e nativeTimestampLongProbe true \
  com.littlebuddy.sim.v2.test/com.littlebuddy.NativeTimestampRunner
```

Require final unique `finished` bundle, `observation_kind=long_60000ms`,
`observation_limit_ms=60000`, `observation_window_ended=true`, actual `continuous_run_ms>=60000`,
accepted/raw sample counts, all original cleanup proofs, JSON `junit_failure=false`, PASS and
JUnit OK1. Missing final result, host command timeout, dependency skip or cleanup uncertainty is
not success. Retain actual elapsed/any overrun; do not relabel a timeout as completion. The command
needs a host observation timeout greater than the fixed worker/cleanup limits, not a modified
sampling budget. Default 3-second command, startup/cadence guards and build/strip/sign procedure
remain unchanged. This advances only 60-second native continuity on the tested device/session;
it does not replace 60-minute complete V2, wake/KWS/child speech/acoustic or functional acceptance.

Filtered artifact packaging also explicitly stores resources.arsc and native .so entries before
zipalign (entry bytes unchanged). This preserves the root's RC8 packaging correction for the
original [-124] install failure; final artifact checks must verify resource storage/alignment and
retained-entry bytes, not just signer/hash. Use zipalign -P 16 -f 4 for this test-only artifact.
