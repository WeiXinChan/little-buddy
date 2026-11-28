# Code37: physically back the existing startup window

Code36's nominal startup window is500ms/8000samples, but its requested native buffer is3200frames with320 reserved. Before a trustworthy stamp, the software worst-case upper bound exhausts its2880 usable frames at roughly180ms if reads have not yet freed enough space. Model initialization is excluded and the pre-JNI boundary is now correct, but moving the boundary or trying the same allocation twice does not repair this contract mismatch.

The code36 phone first capture failed this exact guard (confirmed by the exclusive retry gate); its second STATE_ERROR is not enough to determine its clock predicate. Its event spans147/142ms after STARTUP BEGIN do not identify start JNI or read latency. Missing structured detail is not evidence that no native read occurred. The collector must accept native_start_{before,after}_mono_ms, treat missing optional fields as null rather than dropping the complete row, and retain the exact current scope.

## Bounded physical allocation

NativeCaptureBuffer derives a request from the unchanged clock limits: ceil(501ms*16016Hz)=8025frames,320 reserve,17frames for at least1ms positive room, rounded up to320-frame chunks. The result is8640frames/17280bytes. The platform minimum may require more, but requested bytes remain <=32000 (the previous admitted maximum). This is an AudioRecord constructor allocation, not a fictitious ledger capacity.

After initialization the production code reads actual bufferSizeInFrames and credits min(requestedFrames,actualFrames). An invalid or reserve-sized actual buffer rejects. OEM rounding upward cannot increase credited room; rounding downward cannot borrow the requested capacity. A single RUNTIME_CAPTURE_BUFFER event records requested_native_frames/actual_native_frames/credited_native_frames even on a successful startup, while error context also records requested and actual frames; the ledger evidence capacity is the credited minimum.

The500ms startup deadline and8000-sample cache cap are unchanged, as are timestamp100ms freshness, phase/rate/history/bridge/regression/relabel checks, original coordinates, ring/upload sample capacities and cancellation/release/lease guards. The native buffer may now actually retain a larger continuous interval, but it cannot re-label that interval as fresh PCM. CaptureUploads pins its age to the original6400-byte profile's1200ms ceiling instead of increasing it with allocation. No timestamp indefinitely still fails at500ms with no KWS/upload. JNI beyond the window and real overwrite still fail closed. The code36 single TTL replacement remains bounded; it is not the primary fix.

Requests are at most32KB and neither PCM cache nor queues are sized from an untrusted actualFrames value. The OS may report a rounded native allocation; this value is observed, never used to enlarge application queues or ledger credit beyond the bounded request.

## Verification

Production Capture/NativeReadLedger/Bootstrap with controlled native ports replays35ms start-call cost plus150ms zero-read/UNAVAILABLE warmup. With the old real3200-frame allocation it fails continuity with ledgerReads0/nativeReturned0; with the new real8640-frame allocation it anchors and delivers sample1 without overwrite. This represents the observed failure class, not proof of the phone's exact JNI split. An actual3200-frame result under the larger request must still fail at the smaller room.

The old allocation and enlarged-age code are retained as failing source controls. A baseline-only export of the existing16016/320 constants lets the new resource helper compile; no old Capture allocation or ledger arithmetic is altered. Tests cover500ms missing stamp, over-deadline JNI, actual native overwrite, unchanged100ms age, unchanged upload age and actual/request minimum accounting. Legacy small-native failure fixtures explicitly allocate3200 actual frames so the original loss assertions remain meaningful. No audio content/provider/device call is part of these host tests.

Production NativeTimestampTest uses this same allocation/verified capacity path. Historical timestamp-only/cadence diagnostic sessions keep their original6400-byte profile and original evidence. The test APK requires matching code37 target classes. The default old clarification/service clips, native KWS/AAR/ONNX/keywords and V1 are unchanged.

Code37 must pass exact private-preset/signer/source/resource/zipalign checks before Mac performs one same-signature upgrade, starts the app and observes natural expiry plus current-scope new CAPTURE_READ READY and exact microphone running30s later. Old failed attempts remain in the denominator. Hardware success and the second code36 predicate remain unproven until that measurement.
