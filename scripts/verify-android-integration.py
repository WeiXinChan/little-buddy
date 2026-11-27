#!/usr/bin/env python3
"""Offline provenance checks for this main-base integration; never accesses runtime configuration."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INDEX=json.loads((ROOT/'docs/testing/v2/android-integration-index.json').read_text())
BASE=INDEX['main_base'];FIX9=INDEX['fix9_head']
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)
def names(ref):return git('ls-tree','-r','--name-only',ref).decode().splitlines()
def unchanged(ref,paths):
 for path in paths:
  assert (ROOT/path).is_file(),('missing_source',path)
  assert (ROOT/path).read_bytes()==git('show',ref+':'+path),('source_drift',path)
 return len(paths)
main=names(BASE)
protected=[p for p in main if p.startswith(('backend/','assets/','app/src/androidTest/','app/src/debug/','app/src/v2Debug/','app/src/release/')) or
 (p.startswith('app/src/main/java/') and '/v2/' not in p and not p.endswith('/V2VoiceActivity.kt')) or
 p in {'app/v2-release.json','scripts/v2-release-snapshot.py','scripts/with-build-lock'}]
main_changes=git('diff','--name-only','cf187d4d35490726e3ce996c6cbe3df678a65a67',BASE).decode().splitlines()
# Every main delta since the common RC8 ancestor survives, except three deliberately adapted build files and the extended release regression fixture.
unchanged(BASE,[p for p in main_changes if p not in {'app/build.gradle.kts','scripts/v2-build-metadata.py','scripts/verify-v2-release.py','scripts/test-v2-rc9-preparation.py'}])
protected_count=unchanged(BASE,protected)
fix9=[p for p in names(FIX9) if p.startswith('app/src/main/') and p not in {
 'app/src/main/java/com/littlebuddy/V2VoiceActivity.kt',
 'app/src/main/java/com/littlebuddy/v2/parent/ParentPanelModel.kt',
 'app/src/main/java/com/littlebuddy/v2/parent/AndroidPublicKeyFile.kt'}]
fix9_count=unchanged(FIX9,fix9)
restored=['app/src/main/java/com/littlebuddy/v2/parent/AndroidPublicKeyFile.kt',
 'app/src/test/java/com/littlebuddy/v2/parent/PublicKeyFileTest.kt']
unchanged('7f9544d9f99962c4ce8cef1ec88f611748b2c243',restored)
print(json.dumps(dict(provenance='PASS',main_base=BASE,fix9=FIX9,protected_main_files=protected_count,
 unchanged_fix9_runtime_files=fix9_count,pr122_latest_files_restored=restored,
 resources_manifest_sha256=hashlib.sha256((ROOT/'assets/v2-default/manifest.json').read_bytes()).hexdigest(),
 device='NOT_RUN',cloud='NOT_RUN'),indent=2))
