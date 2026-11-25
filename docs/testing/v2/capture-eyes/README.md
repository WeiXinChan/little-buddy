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

Before another native read, a full queue can wait only within configured native buffer duration
minus one 20ms frame. Cancellation wakes this wait. The native buffer remains bounded at
max(minimum,6400) bytes with minimum <=32000. Delayed reads exceeding this native retention room
fail explicitly. Cached frame timestamps derive from the original native read observation, never
KWS completion or a later upload time; queue freshness is one ring (1000ms) plus configured native
room. Read observation and buffer size are conservative software boundaries, not device timestamp
or acoustic latency proof. No arbitrary sample dropping or unlimited owner backlog.

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
