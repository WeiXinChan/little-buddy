# V2 client phase diagnostics (code32)

Only the existing PIN_INIT_DIAGNOSTICS diagnostic-build switch installs the sink. A normal build creates no phase recorder and never uses diagnostics to start recording. This adds no wire fields and changes no VAD/endpoint, input15s budget, playback, volume, routing, clock, native model or transport policy.

Tag `V2PinInitDiag`, exact stage `CLIENT_PHASE`. All phase times are Android `elapsedRealtime` BOOT milliseconds: `phase_boot_ms` is the owner-side sampled boundary; `received_boot_ms` is WebSocket.onMessage receipt before Handler enqueue (or-1 when not applicable); `captured_last_speech_boot_ms` is the unmodified InputGate.lastSpeech capture boundary (read-only). The formatter's existing `mono_ms` is System.nanoTime MONO milliseconds. `duration_ns` is a MONO elapsed span. Do not directly subtract MONO from BOOT or any phone time from server time. Receipt-to-phase BOOT subtraction measures local callback/owner delay only; socket send=true means OkHttp queue admission, not server receipt.

|phase|observation|
|---|---|
|PROBE_SENT / SEAL_SENT|original gate callback, original send returnedtrue; wire_seq is the existing local outgoing seq, revision is current gate, captured lastSpeech unchanged|
|ENDPOINT_RECEIVED|original gate.decision result; accepted=false explicitly identifies stale/not-accepted wire_revision (or an original thrown deadline check), without treating it as current accepted output|
|OPEN_RECEIVED / BIND_SENT|current revision open processed; original bind send admitted by OkHttp|
|BOUND_RECEIVED|existing player/revision checks and current permitted owner, before original native track construction; receipt time predates construction, accepted denotes scope admission, not ready/audible success|
|TRACK_BUILT|original builder/state/volume/threshold/listener steps succeeded; record min/configured bytes and actual bufferFrames/startThreshold reads; no new setter value|
|TRACK_PLAY / TRACK_PARAMS|duration/success of the existing play and PlaybackParams calls; an original exception still propagates, no retry/fallback|
|FIRST_AUDIO_ACCEPTED|actual player.enqueue returnedtrue and binding/current response revision match|
|FIRST_NATIVE_HEAD_PROGRESS|existing Playback actualOutput(true), itself emitted only on checked native-head advance with pending audio, current response revision/binding; not just a write/enqueue/remote speaking event|

Scope is existing activity/transport/client capture=0. Temporary epoch/revision/wire_revision/wire_seq/stream are numeric only. No session/player UUID, endpoint, configuration/token, PCM, ASR, transcript, exception body or user text. Single numeric binding key; first audio/head flags reset on new bound stream and clear on interrupt/management/close, never an unbounded scope set. Old transport callbacks are rejected by the unchanged socket+active guards; wrong epoch is rejected before phase dispatch. Wrong binding enqueue and superseded revision cannot produce current first audio/head; old track timing closures carry immutable keys and current permission/revision checks. General diagnostics cannot spend phase/critical reservations.

Within original256 rows/15min: normal160 shared general/config+48phase+16critical+32operation. Configuration-only64general+96configuration+48phase+16critical+32operation. Critical includes WAKE_ACCEPTED, clock failure, capture failure/native release/stopend/workerjoin. 61PCM chunks are not61phase events. Exhaustion drops events; no endless retention or new recording. Observer exceptions are isolated.

Collection must preserve exact `CLIENT_PHASE`, `RUNTIME_WAKE_ACCEPTED`, `RUNTIME_CAPTURE_OPERATION`, CAPTURE_CLOCK_DETAIL/LONG_PAIR and existing terminal fixed stages with exact PID/transport filtering. Unknown or missing observations remain unknown, not zero latency. A late/filtered phase is not a successful voice claim.

Offline checks: scripts/client-phase-tests.py (field vocabulary/BOOT-MONO labels/capture boundary/48phase and256total/current binding/dedup/disabled/throwing sink); scripts/test-client-phases-tls.py (actual changed source + cached unchanged production dependencies, JVM platform ports, real loopbackTLS, diagnosticon/off). Default dependencies are the current normal compile; CLIENT_PHASE_CLASSES may point at an existing compile only when remaining dependency source hashes match. No device/provider/model calls in these checks. Host AudioTrack is a controlled substitute, not OPPO proof.

Private code32 is for root independent artifact review and one combined device sampling, not a P12 result. Code31 device observations and older failures retain their original independent denominators. Backend a3e25479 manifest is statically paired; that does not assert deployment or cross-sample attribution.
