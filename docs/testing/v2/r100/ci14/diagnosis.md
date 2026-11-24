CI14 / 3b5bbd3 / artifact14953500523 SHA256 fa674f6e1cefe596f014b6abba713d326402017e4eb3cd048e58165a10921570.

Overall FAIL; Eyes1 (HOME released/return/recreate), pending2, model1, prompt3, stoprace2, completion explicit PASS retained. Completion local/Home stopped at Instrumentation UI-idle wait before lease assertions. Test now uses real Activity launch and resumed/focus conditions without waiting for animation idle. All lease assertions retained.

Mic real focused/READ/head2400 and enter SHA/nonce handshake succeeded; no management enter despite moving frames. No recorded energy or raw KWS/Boundary decision: cannot yet attribute this to recognizer/model. Original emulator.log contains `Could not init pa audio driver` and failed PA context. Upstream emulator headless PA implementation returns NULL for context creation and -1 for connect:
https://android.googlesource.com/platform/external/qemu/+/refs/heads/emu-master-dev/audio/paaudio-headless-impl.c
The build links a separate headless backend:
https://android.googlesource.com/platform/external/qemu/+/refs/heads/emu-master-dev/CMakeLists.txt

This supports a host-routing hypothesis, not proof that runner's exact binary matches that source. Next run records emulator version and Pulse clients/source outputs/sink inputs during each SHA-checked synthetic paplay. Use full GUI/audio backend on task-owned Xvfb rather than -no-window; explicit PA server/source/sink remain confined to synthetic AVD. Owned display/Pulse/emulator cleanup retained. No thresholds/oracles/model changes.

Opt-in instrumentation records aggregate-only one-second PCM RMS/nonzero/peak, finite KWS names/absolute sample positions/config and Boundary geometric decision. Default production has this opt-in false, no PCM copied/stored/exported. No new cloud calls or recordings. First failure includes actual system window/top/keyguard/screenshot and worker stack; cleanup is suppressed under primary failure. Never-started means no worker/lease/recording, not a fabricated native release. Resource-bearing captures still require real release, workerDone, leaseReturned and stable frames.

New dynamic evidence pending: enter pipeline and freshness confirmation pairs are NOT_RUN until actual production mic execution reaches them. Historical oracle failures remain unchanged. v2.1 PREPARING <=6s then real playback completion+200ms publishes fixed8s remains independently conditionally approved, not product acceptance. M06/A01/A27/F01 OPEN, PR36 HOLD.
