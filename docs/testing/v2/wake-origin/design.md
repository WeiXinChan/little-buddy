V2 wake stream-global coordinates

Baseline main: 405c65990e05cf57131fcf2a92a19986049301d6. Original shared
WakeReader/SherpaWake, AAR, models, keywords, thresholds and V1 packaging remain unchanged.
code29 TTL664.327s passed independently; the one synthetic wake failed PLAYBACK_PUMP.
The exact failing pump substep was not observed; the coordinate defect does not alone
prove that specific failure cause.

Disproven path: original1.12.27 C API also reports start_time=0 after automatic resets.
Backend actual0/30s replay and unchanged InputGate demonstrate that adding this field
still expires. Preserve those failures; never use reference clip position/now as correction.

Source fix: fixed1.12.27 KeywordSpotterTransducerImpl::Reset saves the actual decoder
result.frame_offset, performs the identical InitOnlineStream search/model reset, then
restores only that frame_offset. Feature reader/processed-frame counters do not move.
The decoder's existing per-Decode num_frames increments therefore remain stream-global;
its token timestamp=t+frame_offset still comes from actual decoding. New stream starts0.
No silence/keyword threshold, model state policy, sample clock or15000ms response budget changes.
Explicit Reset must preserve this same stream-global origin; V2 closes after first hit.

Build only the keyword-reachable core from fixed upstream source, use a distinct
libwali-v2-kws.so, hide every non-JNI symbol and reuse the original arm64 ONNXRuntime
binary1.17.1/API17 from the unmodified AAR. JNI owns all its model/stream objects;
no old Kotlin pointer, guessed private struct, binary patch or runtime interposition.
Upstream public C++ headers and Android8/API26 jni.h define all ABI input.
Native JNI converts at most320 samples on stack and zeroes them; it only returns numeric
start/last timestamp for the unchanged keyword. Patched engine start_time stays0;
Kotlin requires0, takes real global timestamp + unchanged .12f exclusive-tail estimate,
rounds down and rejects nonfinite/out-of-fed coordinates. No clamp to current read.

V2 copies only five pinned public assets (~5.2MiB) to app-private code cache because the
file-backed source core does not borrow the original asset-manager JNI object. Hash/size,
atomic commit, cancellation and no-symlink checks protect the fixed cache. No audio,
connection credentials or user input is written there. The owner exists before initialize,
so partial/cancelled construction can always close; unconfirmed native close/worker join
continues to quarantine through the existing process recorder lease.

Toolchain: existing LLVM18 host libraries and approved SDK lld; isolated Ubuntu clang
80,040bytes + builtin headers735,998bytes verified against apt SHA. Official r27c ZIP
HTTP ranges select API26/arm64 C++/system headers, static runtime and builtins (~34MiB
expanded), not the whole664MB archive or an SDK install. Every selected entry has ZIP CRC,
size and SHA receipt; whole ZIP SHA is not claimed. Budget native cache<=300MiB,
compilation j1 under scripts/with-build-lock/2GiB. ORT headers are publisher-pinned
1.17.1 from immutable commit f2fcebd1d5560f75d2793af52e13b156cae55c1b; host Linux
runtime remains existing1.23.2 through API17 (not Android runtime proof).

Validation before APK: actual Kotlin->JNI->patched core0/30/90s synthetic replay,
unchanged InputGate, explicit reset, cancellation/zeroing/model cache checks; controlled
production Capture/first-frame origin/replay; ELF machine183/API26/16KiB alignment,
only JNI defined exports, exact original ORT dependency, source/AAR/model SHA and
reproducible source-to-prebuilt binding. Phone/child acoustics and full voice remain OPEN.
Pump diagnostics separate compatibility/management deadline/input response deadline/
player tick/endpoint tick; accepted wake reports only scope/frame/relative time/lag.

Observed source-patched host JNI results (fixed regenerated AIFF SHA04d5cacf...c255):
prefix0: fed17920, tail14719; prefix30: fed499200, tail494719;
prefix90: fed1461760, tail1454719. All pass original InputGate, remaining response
budget~11s. A rebuilt unpatched-core mutant with the identical JNI/runtime yields
prefix30 tail33919 and fails the unchanged cue-window invariant; the first overly
specific negative harness oracle is retained separately. Backend old-runtime result
and original deadline failure are independent, not overwritten by this mutant.
Explicit native Reset in one stream: first tail494719/fed499200; after reset and
10s silence second tail673919/fed678400; both actual model hits, no reference offset.

Offline native rebuild from the already pinned dependency cache:
    scripts/with-build-lock python3 app/src/v2Debug/cpp/build-native.py --cache <native-cache> --arch android
    scripts/with-build-lock python3 app/src/v2Debug/cpp/build-native.py --cache <native-cache> --arch host --host-ort <existing-Linux-ORT>
The cache contains vendor tags/digests in dependencies.json, isolated clang/builtin
headers, selected official r27c sysroot and immutable API17 headers. No implicit
network/download or compiler installation happens during normal Gradle/CI. A fresh
cache requires explicitly obtaining those published, hash-pinned build dependencies;
this is an offline recipe, not a full SDK bootstrapper. Standard release guards bind
all selected native source inputs to the reviewed prebuilt ELF, verify actual APK
bytes/ABI/exports/dependencies/16KiB guards, and reject stale source or extra/missing ABI.
