# RC9/code23 preparation — not a frozen candidate

Prep base: 0279281e71e54bcd981798e76d389c818bd3a13d. Separate branch/checkout; no changes in root's
parent-completion/root-v2-rc8 or backend tree. No device/ADB/install/lockscreen/config import, no Gradle
build, no interaction with old long observation PID3917773 or the root-owned session75560. No new agents, services, keys or deployment.

## Exact release gate and dependency

V2 app/v2-release.json advances 22/2.0.0-rc8 -> 23/2.0.0-rc9 and records this prep base. Generator and
APK inspector BOTH require that exact identity, same application_id=com.littlebuddy.sim.v2 and same
protocol. They also pin RC9 to PR109 f0185497b2df1347a70f494df774a6fdbd1623f3's candidate manifest:

d649ac79bc5203373ff44ebdd547bdd16772663467a22115fa75f589bef91ea1

Root later reported independent visual QA PASS for PR109; this author did not perform that QA.
The repair includes PR109 through normal main60d83a50 integration; the pin alone is not freeze evidence. If QA changes the image or manifest,
update the pin/test projection only against root's reviewed fixed head. No bypass flag, fallback
library, accepting code22/unknown future version, or renaming RC8. The initial prep tree had old resources and was deliberately refused. The RC110 repair now
normally merges reviewed main60d83a50, so corrected source/resource metadata can be checked without
an APK build. This is still Draft and final APK construction remains gated on root approval/lock.
Tests reconstruct only small manifest metadata in temporary unit fixtures (no PNG copied into the
app, no installable APK). They need no unmerged git object in a clean CI checkout. Negative fixtures
include a fully self-consistent RC9-labelled old library, which the inspector must still reject.

Read-only git comparison at preparation time: only star-bunny PNG changes; other59 are byte-identical.
Star-bunny PNG SHA: 4076745a4988a76252df6e05ea42a43e0e62d5f74f7000a0700393d0b8f5082a
Old manifest SHA: 16ec66f3cca282e4070481d803eb8a833f31ee6a1a7733f48bb0948329f1826e

PR106 (544701a256609927e91b246e0403e66a2a4e0322) and its dependent PR108/109 were unmerged on initial
read. Root later reported PR108 final f5b38d4 independently23PASS and PR106 awaiting its second CI.
Root must complete the normal dependency review/merge sequence (including any reviewed
successor to PR108) and this version PR, then use the latest clean integrated main Android code.
Do not cherry-pick/copy the pending resource tree or pretend this minimal version PR integrates it.
No final candidate before PR109 QA+merge AND root releases the actual heavy-lock/build gate. Final source SHA/tree comes from actual integrated main;
source_base is the prep/fork baseline, not a substitute for final commit or inventory digest.

## Existing identity/signing, V1 separation and upgrade

Existing RC8 archive: bc8e7869db1329655e5d78a56a656c27c191038fa9c80df3cb7e4e9f23918422,
code22/2.0.0-rc8, com.littlebuddy.sim.v2. Root's archived public signer SHA256:
7705f543347ae9ec1de4ae4b0dc24f73b0a472fb32ecc06cca0d112a8fe75e10.
Read public APK/signature evidence only; no keystore/private key export/readback or new signer.
Existing v2Debug initWith(debug), applicationIdSuffix .v2, arm64-v8a/min26/target36 remain unchanged.
V1 default applicationId=com.littlebuddy.sim/code13 is untouched; buddyVersion overrides still target
release only. RC9 must reuse existing signing process/key internally, then verify public certificate
from the produced APK equals RC8. No re-signing with a substitute key to make a check pass.

23>22 with same package and signer is the static prerequisite for in-place upgrade; this preparation
does not prove actual install or record retention. Root will coordinate authorized automation only
after the phone is explicitly ready tonight. Do not uninstall/clear data/change owner/lockscreen to
force success. Lower-code rollback is not guaranteed/permitted as ordinary upgrade; retain the
original APK and records, let root decide any rollback separately. User only final whole experience.

## Freeze only after review/merge and clean integrated tree

1. Record actual main SHA/tree and dependency merged heads. Confirm corrected manifest SHA, all60
   PNG/512 dimensions/SHA, star-bunny exact payload, and other59 unchanged against reviewed baseline.
   Existing prepareV2Images checks remain unchanged; preserve actual asset receipts in final report.
2. Generate deterministic v2-build.json/source inventory from that tree using original selected-file,
   public transport pins, unexpected untracked source/asset and secret exclusion checks. Record
   source_content_sha256/build_id/resource hash. No environment/paths/credentials in version metadata.
3. Under the one scripts/with-build-lock, max-workers1, use existing SDK/cache:

   scripts/with-build-lock ./gradlew --offline --no-daemon --max-workers=1 :app:assembleV2Debug

   This command is intentionally NOT executed for the prep branch. Keep existing signing identity.
4. Final aapt badging must read com.littlebuddy.sim.v2, code23, 2.0.0-rc9, min26/target36/arm64; verify
   apksigner and public certificate against RC8. Verify resources.arsc storage/alignment and exact
   embedded source inventory/resources; hash the actual new APK, never rename an old archive.
5. Run scripts/verify-v2-release.py --apk <new-APK> --backend-manifest <reviewed-actual-manifest>.
   A backend archive still declaring old16ec library is incompatible with corrected d649 RC9. Root
   must supply a matching reviewed backend release manifest (same protocol, new asset inventory);
   never edit evidence/fake manifest to pass. No backend deployment authorized by this preparation.
6. Attach actual APK/SHA, fixed SHA/tree/build ID/inventory, asset receipts, version/appId/public
   signer/upgrade prerequisites and actual checks/skips/remaining R/A/P acceptance. No CI/host check
   replaces phone/owner/whole-product or long observation evidence. No test list for the user.

## Preparation-only checks

python3 scripts/test-v2-release-compat.py
python3 scripts/test-v2-rc9-preparation.py

Existing5 protocol/resource pairing methods plus8 new offline identity/inventory/resource guards.
The latter uses temporary mini git source trees and ZIP metadata fixtures explicitly NOT installable
APKs. Tests cover RC9 correct identity, reject old/unknown/mislabelled version, old library despite
relabelled RC9, tampered inventory/local source drift, uninventoried files and backend hash mismatch.
They do not certify PR109 artwork, signing/upgrade or final integrated APK.

## Root scheduling update (not an author-run test result)

Root reported old session79841 ended normally (120 attempts/0 failures/cleanup0 pending), and a new
independent TLS-fault long observation session75560 started10:22UTC holding the SAME heavy.lock,
expected around11:22UTC. Author did not inspect/interrupt either session. Do not acquire another
lock, bypass it or loop build retries. Expected elapsed time is not proof lock was released and not
approval to start a build. This PR remains light preparation; root coordinates the single final
heavy APK build only after actual release AND PR109 integration. No phone/ADB actions.

## RC110-01 / RC110-02 repair

This branch normally merged main60d83a50b5d8cd54ff78bcda30460907265488aa (106/107/109); source_base now
records that integration baseline. PR108 f5b38d4 is still pending CI and is NOT claimed included or
deployed. Root's stated deployed backend is050b9a93 compatible with RC8; no deployment was performed.

The shared trusted scripts/v2-release-snapshot.py defines selected membership and independently
uses current git ls-files PLUS physical selected directories/exact files. Untracked/ignored selected
files and symlinks refuse; private extensions are refused before reading. Generator AND inspector
use it. Incoming self-reported inventory must have exact complete keyset and exact sha256/size
receipts with integer sizes; canonical digest/build ID and all release config fields must match the
independent current snapshot. Removing an entry and recomputing self-digest cannot authorize omission.
Gradle metadata task inputs and source inventory include the new helper so changes invalidate output.

Before generating anything, validate actual60 SVG and60 PNG against pinned manifest source/png SHA,
SVG512/viewBox and real PNG IHDR512/size/signature; require exact local source/png file sets. APK
inspection requires exact61-entry v2-default namespace (manifest plus60PNG), exact bytes against
trusted validated local resources and globally unique ZIP names. Missing/extra/wrong payload or
repeated entries fail, even if all self-reported digests are recomputed. No image/version pin relaxed.

Offline checks now:5 existing protocol methods,15 candidate guards (8 previous+7 closure/payload
methods) and QA's3 ORIGINAL independent inputs/assertions replayed unchanged. Those QA cases are
separate, not counted as newly authored method coverage. Mini git/ZIP fixtures now include the full
reviewed60-resource library; they remain explicitly NOT installable APKs. Original3FAIL is retained.
The final local positive path generates metadata/inventory for the merged real tree and inspects a
synthetic metadata/resources ZIP only; no final APK, heavy build, phone or server deployment.
