# Native timestamp driver probe (not executed on device by author)

Base main33af6923. Only androidTest and this procedure change. Main/v2Debug, frozen code20rc6,
production NativeReadLedger and every threshold remain byte-for-byte unchanged.

## Explicit test-only isolation

Select `com.littlebuddy.NativeTimestampRunner` (additional instrumentation in the test APK manifest),
not the default SimUiRunner. Default runner behavior is unchanged. This runner substitutes a plain
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
Java test preflight. Do not run it against any live target PID; do not use force-stop/kill to clear a
business process. The root's exclusive-device reservation must prevent another app launch between
that check and instrumentation. `--no-restart` is not a substitute: on AOSP it instruments an existing
process rather than creating this isolated Application; our Application identity check then refuses.
See [AOSP instrumentation implementation](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android15-release/services/core/java/com/android/server/am/ActivityManagerService.java).

## Exact invocation for root AFTER source review, on the one reserved device

Install only the matching-signed test APK alongside root's already-installed code20 candidate.
Do not replace the frozen target APK with a local app build. Read current PID/permissions/display
state first. If any target PID exists, a capture/other test is active, the screen is locked, or
permission/foreground is unavailable, retain DEPENDENCY and defer; do not reset data, credentials,
lockscreen, grant parent rights, contact users for point tests or silently downgrade checks.
RECORD_AUDIO can be granted through root's existing authorized test-permission flow before launch;
the test never grants permissions/unlocks the screen itself. Do not grant via a PIN/Grant bypass.

```sh
# SERIAL and TEST_APK are chosen by root, not by this author. No commands executed here.
adb -s "$SERIAL" shell pidof com.littlebuddy.sim.v2
# Require empty PID output; if nonempty STOP this direction, do not force-stop.
adb -s "$SERIAL" install -r "$TEST_APK"
adb -s "$SERIAL" shell pidof com.littlebuddy.sim.v2
# Again require empty; root holds exclusive device and no other launch/test in between.
adb -s "$SERIAL" shell am instrument -w -r \
  -e class com.littlebuddy.NativeTimestampTest#nativeTimestampAndProductionLedger \
  -e nativeTimestampProbe true -e businessIdlePreflight true \
  com.littlebuddy.sim.v2.test/com.littlebuddy.NativeTimestampRunner
```

Save this selected instrumentation stdout as METADATA ONLY. Do not collect full logcat, PCM,
recordings, transcripts or environmental content. If the device's am tool supports --no-logcat,
root should add it to suppress generic crash-log attachments; lack of a privacy-safe invocation
must be reported rather than collecting unrelated logs. Never invoke the default runner and
interpret this probe's dependency skip as a driver pass. Runner forces disableAnalytics=true.

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
ended before any further device work; no automatic business force-stop is part of this procedure.

Accept only final status-code7 Bundle `v2_timestamp_phase=finished`, `v2_timestamp_outcome=PASS`,
real stopped/released/worker_joined/stop_task_joined true, lease released, continuous counts above,
AND JUnit OK1. Progress NOT_EXECUTED, failure or dependency skips are never hardware success.
Counterexample metadata retains the exact body-free production ledger reason. Native exceptions
are identified by class/phase/API/read status, not arbitrary message/body/logcat. If no native API
success, age sentinel Long.MIN/MAX means not observed. This does not prove acoustics/ASR/child speech,
network/SSH, owner/PIN/Grant, or production conversation/lifecycle integration.

## Local preparation

Use existing SDK/cache, no dependency installs:

    bash scripts/with-build-lock env ANDROID_HOME=<SDK> ANDROID_SDK_ROOT=<same> ./gradlew --offline --no-daemon --max-workers=1 -Pv2Test :app:assembleV2DebugAndroidTest

Inspect the merged androidTest manifest for BOTH default SimUiRunner and the explicit new runner,
targetPackage com.littlebuddy.sim.v2; no test APK Activity declaration. Inspect/sign/hash
app/build/outputs/apk/androidTest/v2Debug/app-v2Debug-androidTest.apk. Report exact source SHA/tree,
artifact hash/signature/runner and build result. Building the test APK does not mean OPPO execution.
