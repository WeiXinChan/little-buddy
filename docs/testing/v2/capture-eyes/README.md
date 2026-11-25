# Current-contract capture and eyes repair

Base b5be01b4 (not PR36). No old management prompts, model thresholds, public configuration,
version identity or APK freezing changes. V1's shared SherpaWake only gains an optional allowed
callback defaulting to true; paths/keyword/threshold/timestamp formula remain unchanged.

## Ownership and cancellation

ProcessRecorders is common to Capture and ManagementCapture. Acquire precedes worker/native/model
construction. Native release, model disposal, actual worker join and every stop task must each
complete before another lease is granted. RecorderLease diagnostics distinguish these proofs.
Constructor/disposal/release uncertainty keeps the process fail-closed; no timeout grants ownership.

HOME/focus loss invalidates recorder generation and calls requestCancel directly, before parent
page cleanup and independent of the owner Handler. It wipes queued PCM and launches a stop request
against only that instance's native handle. Native stop/release is serialized against that request
and happens before model disposal. close still has a bounded join; an alive or uncertain worker
quarantines the local instance. A separate join observer confirms real thread death. Cancellation
cannot interrupt a JNI call already blocked; a blocked native stop/start/release/model destructor
may retain the lease indefinitely. No automatic restart bypass exists. Failed resource confirmation
requires diagnosis/process recreation, not assuming success after 500ms.

## Audio continuity

CaptureUploads owns batches up to the 16000-sample ring capacity, with exactly one scheduled drain.
Overflow, refused post, stale data and consumer failure wipe queued and rejected/unposted arrays.
An in-flight consumer's current array is wiped in finally; cancellation cannot retract IO entered
before cancellation. VoiceClient retains its own lifecycle/management gate.

NativeReadLedger uses cumulative `AudioRecord.getTimestamp(TIMEBASE_MONOTONIC)` framePosition
minus cumulative successful reads, not elapsed-time-at-16kHz since start. Every read/wait/KWS/model
step consumes the same remaining room; successful reads only credit samples actually removed.
A 320-sample guard remains below the configured native buffer; buffer size is not enlarged.
Native counter snapshots are checked before and after read and before wake/batch admission.

API24+ provides this capture frame/time pair and may report it unavailable; frame count resets on
restart ([AudioRecord API](https://developer.android.com/reference/android/media/AudioRecord#getTimestamp(android.media.AudioTimestamp,%20int))).
`TIMEBASE_MONOTONIC` is System.nanoTime's timebase; recorded sample times come from the hardware pair
([AudioTimestamp API](https://developer.android.com/reference/android/media/AudioTimestamp)).
CaptureMonotonic uses that exact clock. An immutable conservative bridge to elapsedRealtime is
sampled BOOT-before-MONOTONIC, checked for >5ms drift/suspend; it is never rebased to freshen audio.

Missing startup stamps permit no reads/uploads and only a bounded native-room startup wait. Once
primed, the prior pair may be extrapolated only while <=100ms old (or less for a smaller buffer).
No timestamp resets the read count. Positions/times must be monotonic, stationary positions may
not receive a new time, and observed rate must remain within 15984..16016 frames/s (+/-1000ppm,
with two-PCM-sample quantization allowance, not two320-sample batches). This short-window rate bound is explicit; it is not a
session-long assertion of exactly 16kHz. New snapshots account for hardware drift directly, including
600s +/-100ppm tests. Missing/stale/incoherent/out-of-bound clocks fail closed, not software fallback.
Hardware timestamp availability, estimates, driver semantics and real oscillator error remain OPPO
validation gaps. These tests do NOT certify acoustic/native continuity on a physical device.

PCM times use the original hardware frame coordinates and conservative lower-rate lookback (plus
bridge rounding), not read-return, KWS completion or upload time. The <=16000-sample ring and native
buffer remain unchanged. An already-blocked JNI call can overrun native storage before returning;
on return the cumulative check fails before further wake/PCM admission, cancels and wipes buffers.
No claim is made to interrupt that JNI call or physically prevent hardware overrun inside it.

On re-wake, the current frame is already pushed: the new KWS origin is position-count, i.e. its
first actual sample. Existing absolute ring and 2560-sample pre-roll behavior are retained.

## Eyes and production wiring

V2EyesView renders eight distinct geometries/colors from EyeState. The daily surface remains two eyes,
with existing picture overlay/hidden gesture; parent PIN/Grant and FLAG_SECURE are untouched.
Activity checks foreground/focus, transport generation, page generation and recorder source.
Capture emits recording state after native recording is confirmed. VoiceClient observes Playback;
PLAYING begins only after the local native playback head advances, not on server speaking or even
on AudioTrack.play(). Pause, queue exhaustion and stop clear that evidence. Activity ignores queued
old callbacks after HOME/management/page replacement. These are playback-head observations, not
proof of audible sound, route quality or a nonzero parent volume.

## Targeted verification

Run offline under scripts/with-build-lock:

    python3 scripts/test-v2-capture.py

It compiles actual Capture/ManagementCapture/Playback/ring/lease/reducer against controlled
Android/native substitutes (no device/microphone). OriginalCaptureTest retains the original six behavioral assertions between old
baseline and repaired production source (and strengthens wake-before-batch ordering): 21/50-frame delayed owner, cross-instance overlap,
child/management mutual exclusion, native-before-model cancellation, re-wake coordinates.
The baseline is exported from git b5be01b4, not a handwritten faulty reimplementation.
Safety tests add zeroization, failure, post rejection, bounded wait, native constructor/start
races, blocked management decode, actual playback-head-to-eye reducer transitions and stale tokens.
A separate stage compiles the real shared WakeReader/SherpaWake against the controlled decoder,
checking default wake timestamp and cancellation before/after every decode boundary.

SDK compile is :app:compileV2DebugKotlin --offline --no-daemon --max-workers=1 -Pv2Test.
Compiled Activity/View/VoiceClient bytecode is retained as wiring evidence; neither that nor pure
geometry tests prove Android Canvas output, OPPO recognition, JNI behavior or speaker acoustics.
No APK is produced/frozen here; root owns the final combined identity and final device validation.

R02 signal map: compatibility -> CONNECTING (no claim of capture); confirmed native recorder +
compatible wake -> WAITING_WAKE; InputGate speech/wake -> LISTENING; accepted endpoint COMPLETE,
INCOMPLETE, THINKING -> WAITING_CHILD until actual seal. InputGate seal/solo -> THINKING (robot
response pending), whereas a child thinking invitation remains WAITING_CHILD until actual prompt
playback. A reply completion returns to the current InputGate waiting state. Native head progress
-> PLAYING; pause/exhaustion/stop clears it. Local failure/incompatible/unknown code -> FAULT even
without a recorder; clarify -> WAITING_CHILD only with confirmed capture. These states are visually
separate and never turn server speaking into native playback. Local help/parent/image pages may
cover the eyes; the reducer cannot claim their rendering or actual acoustic state.

### R75-01 evidence and coordinate oracle

The 14b7b20 baseline uses actual Capture against a continuously producing, real-process-time native
FIFO: 16kHz production, independent read calls and a 3200-sample native capacity. Each 100ms KWS
step is individually below 200ms yet accumulates unread data; the baseline silently overwrites
samples and reports no failure. Short 60ms burst then catch-up is the positive control; a third
case proves backlog sample age is not the later read-return time. Original baseline logs are retained.

Original finite fixtures previously froze the clock at100000ms. The original re-wake oracle99980ms
meant current time minus the already-fed320 samples; buggy origin gave100000ms. The finite fixture
now advances20ms per320 samples: first frame starts100000ms, second frame starts100020ms.
The sample-coordinate oracle is therefore origin+320/16, with a conservative 2ms hardware/bridge
rounding interval. It still rejects the original extra-count shift (100040ms), and does not change
ring cursor/tail samples or weaken the21/50-frame assertions. The separate continuous fixture uses
actual process time, not that finite-source clock. Pure ledger checks additionally cover hardware
rate bias over600s, start delay, timestamp loss/staleness, counter/rate/clock errors and unread budget.

Timestamp provider calls are bracketed by monotonic reads; all age, future and remaining-room checks
use the post-call mono/boot observation. API/JNI delay is charged to the same cumulative budget.
Two controlled provider-clock tests cover a legitimate later new pair and an old pair that loses
room and expires while the API is delayed. The continuous native fixture also blocks the first
getTimestamp call for80ms while production continues: a valid fresh pair must not be rejected as
future simply because it postdates the pre-call observation. No future tolerance is enlarged.
