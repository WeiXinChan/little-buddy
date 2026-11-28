# Normal expiry: bounded capture startup recovery

Observed code35 PID16533 expired normally at600.063s, released its old recorder/worker, then reached new protocol READY. New Capture failed STARTUP_NATIVE_CONTINUITY_EXHAUSTED. Its1657ms start-event span includes model work; model initialization was205512792756556..205514178137480ns. The relevant ledger origin205514178ms to check205514359ms is181ms. Capacity3200 minus reserve320 gives2880; softwareUpper=ceil(182*16016/1000)=2915. Accepted ledger reads<=35 therefore trigger continuity exhaustion. These facts do NOT identify the native start-call duration or prove zero native reads: returned data may have failed admission before ledger credit. There was no valid hardware stamp; frame/stamp zeros are not hardware observations.

## Changes

A one-shot armNativeStart is called inside the per-Capture native lock immediately before startRecording, after prefix allocation and final allowed check. Only known pre-call setup is excluded from the possible-production interval. The entire unknown JNI/start interval, every timestamp/read delay,500ms startup deadline/8000samples,3200 native capacity/reserve,phase/rate/age/bridge/history guards remain charged. The method cannot run twice, after any observation or accepted read. It does not reset hardware coordinates, accepted reads, clock envelope or BOOT bridge; the hardware-origin lower bound uses the actual pre-call boundary. sampleTime retains the original conservative bridge mapping.

A separate one-shot retry is armed ONLY by an accepted current-scope session_expired after complete old transport/capture release. It binds the new transport and its first recorder ticket. On STARTUP_NATIVE_CONTINUITY_EXHAUSTED only, the handler closes/confirms that recorder, model worker, independent stop task and ProcessRecorders lease. Foreground/focus/unlocked/permission/route, same client/scope, idle waiting-wake (no input/output/binding), unquarantined output ownership and full release must all still hold. It then constructs one completely new Capture. No network retry is performed; that new transport's TTL keeps aging. No unanchored PCM is admitted, retained, or replayed into a later recorder. The fresh instance starts its own real sample0; old failed counters remain in diagnostics.

At most two recorder attempts occur for that accepted expiry: first plus one replacement. Persistent failure goes through the existing HOLD/release path. Other failures (including stale timestamps, phase/rate/bridge faults and release uncertainty), ordinary startup, stale tickets, management/focus/lifecycle changes do not borrow this permission. Lifecycle/management/whole-transport retirement cancels it. Duplicate old failure callbacks cannot affect the new captureRevision. Original15s input/600s session/P01/native buffer policies are unchanged.

## Measurements

Existing CAPTURE_CLOCK_DETAIL gains fixed numeric context fields (no new per-read log rows):

- native_start_before_mono_ms / native_start_after_mono_ms: pre-JNI boundary and return, floor MONOTONIC milliseconds, -1 when not reached.
- native_read_calls: actual read invocations, including an in-flight/throwing call.
- native_returned_samples: sum of positive returned native counts before ledger validation; not accepted/uploaded PCM.
- last_native_read_count: most recent returned count, -1 until a call returns.
- prefix_cached_samples_total: historical accepted-to-cache startup count, retained after cache clearing for evidence; NOT currently retained PCM.

NATIVE_START is a fixed operation enum. Existing operation_before_ns/operation_after_ns/last_operation now also record the actual last native read (not merely the last model operation); only slow reads use the already bounded operation trace. EXPIRY_CAPTURE_RETRY is a fixed runtime event on the failed physical recorder scope; a following new CAPTURE_START has a fresh capture ticket. Existing RELEASE/WORKER_JOINED evidence still proves the previous lease ended. Original256-row/15min cap remains. Collectors must add these enum/field names without reading raw log content.

## Evidence and limits

The same controlled production-Capture regression fails on main12d1b1f for a181ms final pre-start admission delay; model-only initialization and start/read delay negative controls remain separate. New code preserves sample1 in the successful model/pre-start paths. Native start AFTER arming and returned-read delays still reject; a new test demonstrates nativeReturned320 with ledgerReads0 and no cached/uploaded PCM. Exact181ms boundary fixtures cover ledger reads0/35/36/52.

Expiry tests execute real Capture/ledger/bootstrap/lease with controlled native/KWS ports: released old instance -> failing fresh recorder -> one replacement -> anchored sample1; persistent failure; cancellation/missing release; wrong scope/awake/non-startup/ordinary startup refusal. These are not Android hardware/real-ONNX evidence. The phone's precise split between pre-call scheduling, native start, read/JNI delay and hardware unavailable remains unknown until the new fixed scalars are observed. The patch fixes a proven pre-start accounting error and bounds recovery from a still-valid post-start rejection; it does not declare a vendor clock fault solved.

Candidate source version36, nopin.startup1, retains the same package/signer workflow/private preset/noPIN settings and device identity. Production timestamp instrumentation uses the same pre-native arm inside its cancellation/start lock; its updated test APK requires the matching new target classes, not code35. All original device and WIP failure records remain unchanged. No device/cloud/deployment is part of author verification.

The failed first replacement attempt remains a recorded CAPTURE_FAILURE/CAPTURE_CLOCK_DETAIL, even when the one fresh retry succeeds. EXPIRY_CAPTURE_RETRY distinguishes it from final HOLD; FAILURE_UI_APPLY is emitted only when the UI really enters the failure path. Device reporting must retain per-attempt failures rather than relabel the whole interval as zero-failure.
