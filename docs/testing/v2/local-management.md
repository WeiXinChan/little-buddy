# V2 local management (user-requested removal of PIN)

VersionCode26 replaces the unused code25 candidate. The right-bottom hold opens management directly. No PIN, system credential, enrolled fingerprint or secure lock screen is required. Other long holds still do nothing; verified server safety-help events remain supported. This is deliberately a discoverable local settings page, **not authenticated parental control**. Anyone using this device can enter it.

Production `AndroidParentRuntime` selects explicit `localManagement`; `AndroidParentPanel` never creates `AndroidOwnerPrompt`. Page capabilities retain final write/admission checks, lifecycle/feedback revocation, stale callback rejection and the 120-second local idle bound. Re-entering from the corner creates a fresh capability. No system-owner receipt is simulated. Legacy PIN methods remain only for backwards-policy tests and reject under local policy.

## Storage migration

The PIN was a verifier, not the encryption key. Schema1/2/3 ciphertext is opened using the **existing** `little-buddy-v2-parent-v1` AES/GCM key and the unchanged AAD derived from the old owner's **public certificate**. No signature, authentication prompt or private owner key is used. Migration commits schema4 atomically: no salt/hash, no retry penalty; the volume/rate/duration and exact stored connection identity/credential remain. Missing connection can use the already-authorized private preset, without overwriting an existing connection. Empty schema4 is exactly33 bytes.

Fresh installs use `v2-app-local-management-v1` as public AAD and an exact one-byte noBackup selector. Unknown/corrupt markers and existing stores missing both the original certificate and valid local selector reject. A missing key, unauthentic ciphertext or storage failure quarantines; it does not initialize over or silently discard the old record. This cannot recover genuinely lost ciphertext keys. Removing the screen lock alone is **not evidence** those keys are lost.

The AES store key and SSH `buddy-ssh-device-v2` RSA alias do not request user authentication in their creation specifications. They are not regenerated or modified by this migration. Actual target key availability is not established by JVM tests. SSH/Bearer server authentication, fixed host key/CA, endpoint confinement and device registration are unchanged. No secrets are added to tracked source or public evidence.

Schema4 is intentionally unreadable to earlier PIN-only versions. Do not promise rollback to them as a supported data-preserving operation. Do not uninstall, clear app data, rotate aliases or re-register a key to hide a migration error.

## Evidence boundaries

Tests exercise real ParentDomain/Codec/SealedParentStore and ParentPanelModel: fresh local policy, legacy1/2/3 migration, cooldown removal, exact connection retention, repeated entry, lifecycle/idle revocation, late queued open, corrupt ciphertext, unknown marker and missing certificate. Android compilation confirms wiring types; it does not prove target Keystore accessibility, rendering, capture continuity or voice interaction. The bracket clock fix, original 100ms freshness and all original continuous-sampling gates remain intact.

Root performs the eventual same-signer update and no-PIN UI check, then a separate bounded clean-launch capture observation; the author does not install or operate the phone.
