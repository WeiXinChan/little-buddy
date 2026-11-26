# Real packaged wake JNI fixture probe (test-only)

Base 9dd265e7ec6073b6ddd7a0568da67fe191ab1e05. Existing WakeUploadTest's silence case shows the
correct SherpaWake(target.assets) constructor, but has no exact isolated runner, known positive
fixtures, target/fixture digest check, foreground/lease/cancellation or quarantine proof. Reuse that
production class and its actual KeywordSpotter/ONNX; do not duplicate/shadow model classes or
use WakeReaderTest's controlled keyword. No production source, defaults, model files or version edits.

Separate NativeWakeModelRunner selects only NativeWakeModelTest#packagedProductionModelOnFrozenFixtures
and three explicit true flags: nativeWakeModelProbe, businessIdlePreflight, knownWakeFixtures.
Ordinary/default runner and all NativeTimestampRunner/3s/60s/startup/cadence allowlists remain unchanged.
A test-only init script selects the new runner for assembleV2DebugAndroidTest only. Plain Application
and blank foreground substitution use the target's already declared V2 component/UID. No business
Activity/Application, ParentDomain, owner credentials, AudioRecord, playback or network construction.
Permission to run this native port instrumentation is not a business owner Grant.

Root must record real idle preflight/exact package identity/single-device ownership before invocation;
unknown/active capture/management/draft must not be displaced. The target ProcessRecorders lease is
acquired before Activity launch and held until actual worker join AND all model close returns.
Native-recorder release is explicitly N/A (never allocated), not fabricated AudioRecord evidence.
One worker, four independent production SherpaWake streams, sequential close before the next model.
No concurrent close/decode. A constructor that throws after attempted allocation, a close that throws,
or an unjoined JNI worker leaves models/lease unconfirmed and FAIL/quarantine. Java cannot physically
interrupt a stuck JNI; cancellation sets the production allowed callback false, clears test scratch
immediately, and finite worker joins do not turn missing proof into success.

Hash the five exact target assets (three ONNX, tokens, keywords) and three exact test PCM fixtures
before any model construction. Digest/size allowlists are fixed in test code, match source assets and
scripts/wake-fixtures.sha256. Read fixed PCM16 little-endian in <=320-sample chunks, zero buffers in
finally and on caller cancellation, never log samples/content/keywords/transcripts. Synthetic silence
is 32000 samples. command-alone consumes its entire frozen input with no hit. wake/gap-120 each must
produce a real hit; stop on the first hit, as production SherpaWake is a one-hit stream, and require
0 < raw exclusive tail <= samples actually supplied <= exact fixture samples (no coordinate clamp or
invented origin). Fresh streams start at sample0. Record only case IDs, hashes, hit/tail/feed counts,
wall/process CPU and construction/close/join/lease metadata. No acoustic/Capture tail replay claim.

Fixed total kernel wall budget60000ms, process CPU45000ms, model attempts4, input cap229448 samples
(silence32000 + exact fixture sample counts). Check before/after hashes, constructor and every accept;
observed overrun/hash/hit/sample invariant is a typed FAIL even if foreground is subsequently revoked.
All close calls run regardless of cancellation/budget. No host paths/URLs/duration/PCM overrides or
automatic retries. Join worker65000ms plus original bounded1500ms cancellation cleanup; unconfirmed
release dominates clean dependency skip, using shared ProbeDecision/enforce policy. These are bounded
observation/joins, not an assertion that JNI can be killed or CPU across native libraries proven.

Dedicated known-fixture distribution mode keeps ONLY the three allowlisted PCM assets after exact
hash validation, rejects other audio, stores/aligned resources/so, and preserves all remaining entry
payloads. Default timestamp artifact stripping remains audio-free. Final DEX must not define
SherpaWake/KeywordSpotter/NativeReadLedger/other target business classes. Sign with existing debugkey,
no business APK freeze. Host fakes test only guards/policies, never substitute evidence of ONNX/JNI.
Compile locally; QA/root arrange exactly one device run after review. This probe does not establish
microphone acoustics, child speech, actual Capture wake first-word replay or complete wake/session flow.
