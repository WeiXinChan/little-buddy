# code27 configuration-only diagnostic

code26's actual device failure is retained: all attempts reported NO_CONFIG; no WSS/capture occurred in420.065 seconds. This is not evidence of either success or failure of the bracket clock correction. The existing report cannot identify the missing configuration stage.

The same production AndroidParentRuntime now delegates its platform-independent sequencing to ParentRuntimePath. Android's adapter continues using Context/noBackupFilesDir, original certificate lookup, AndroidParentDomain, AndroidParentStore/AtomicFile and Keystore. No reset, alias regeneration, fallback binding, auth weakening or new connection is added. Runtime startup reports distinct LOAD_FAILED/MIGRATION_FAILED/CHILD_MISSING/NO_CONNECTION. Obsolete parental-auth wording is removed.

`CONFIG_DETAIL` records only monotonic milliseconds, a process-local attempt counter, fixed phase and fixed reason. Phases cover worker, store presence, legacy alias/certificate presence, marker read/select/write, domain opening, store/key read, preset, migration/commit and child read. The certificate hash/binding, alias names, ciphertext, keys, token, endpoint, messages and stacks are never event fields. IO exceptions in commit retain their exact types; diagnostic sink errors are isolated. The15-minute process lifetime and256-row total remain. Configuration-only builds reserve96 of those rows for CONFIG_DETAIL, leaving160 for other events; noise cannot consume that reserved budget.

## Dedicated artifact

VersionCode27 /2.0.0-rc9.nopin.diag2. Build flags:

    -PpinInitDiagnostics=true -PprivateDevicePreset=true -PconfigurationDiagnosticOnly=true

The last flag requires the first two, is false by default, is represented in metadata and requires explicit release-verifier admission. The dedicated candidate returns after configuration checking, before WSS setup, RECORD_AUDIO permission requests or capture. READY therefore means only that an existing configuration was read. The app remains on eyes; no management or speech exercise is needed. Do not merge this diagnostic candidate into main as a completed fix.

## Root/Mac single-run plan

Only root coordinates the exact APK/signer/hash update. Preserve app data and all aliases. Collect the dedicated V2PinInitDiag tag with the existing fixed allowlist; add CONFIG_DETAIL fields `mono_ms,attempt,phase,reason` and fixed CONFIG result enums. Never retain unrestricted logcat/UI dumps. Use a fresh controlled diagnostic process within its15-minute logging window. One clean launch, at most30 seconds; no management entry, voice workload or420-second wait. The diagnostic gate prevents automatic WSS/capture even if configuration becomes READY.

Expected distinctions: LEGACY_CERT ABSENT then BINDING STATE; LEGACY_CERT SECURITY/OTHER; KEY_LOAD INVALID_KEY/ABSENT; STORE_READ BAD_TAG/IO; MIGRATION BUSY/QUARANTINED/REJECTED; PRESET ABSENT/ARGUMENT; CHILD_READ EMPTY/NO_CONNECTION; or READY. Preserve the first failing stage and attempt, not only the final empty result. Actual hardware behavior determines the next fix; no cause is asserted beforehand.

## Local evidence boundaries

AndroidRuntimeConfigurationTest invokes the actual AndroidParentRuntime typed platform entry, real ParentDomain/SealedParentStore/ParentCodec/ParentEnvelope, real JVM AES/GCM, temporary ciphertext files and atomic replacement. Platform IO is controlled: it is not a real Android Keystore/AtomicFile/Context test. It covers successful old-record migration without system credentials, fresh/preset/reload, missing certificate, certificate API failure, invalidated/missing key path, corrupt ciphertext, unknown marker, missing connection, commit failure, child read failure, diagnostic sink failure and reserved row budgets. Existing local-management/key-store tests remain. The standard Android compilation checks real adapter wiring; the target diagnostic establishes actual certificate/key availability.
