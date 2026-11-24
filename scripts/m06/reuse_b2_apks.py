"""Explicit one-experiment b2 artifacts, NOT a generic APK reuse optimization.
Every tracked difference outside this reviewed host-only scope is rejected.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

SOURCE='b2ccf61d3ef002aa0b43cc488627d21038f4fdfc'
SPEC={
 'app-v2Debug.apk':('7b9e5d7f988e40f33761f6664920c44b48a52901179ed841f0fbbe2bd791f47a','app/build/outputs/apk/v2Debug/app-v2Debug.apk'),
 'app-v2Debug-androidTest.apk':('0b5db56484d287ca93ab5e39e34d885acb363b12f5dd5fc3123205b61fc59444','app/build/outputs/apk/androidTest/v2Debug/app-v2Debug-androidTest.apk')}

def host_only(paths):
    return all(p=='.github/workflows/v2-eyes.yml' or p.startswith(('scripts/m06/','docs/testing/v2/r100/ci24/')) for p in paths)

def verified_copy(root,spec=SPEC):
    root=root.resolve();found=list(root.rglob('*.apk'))
    if len(found)!=len(spec):raise ValueError('APK file count mismatch')
    verified=[]
    for name,(expected,destination) in spec.items():
        choices=[p for p in found if p.name==name]
        if len(choices)!=1 or choices[0].is_symlink() or not choices[0].resolve().is_relative_to(root):raise ValueError('APK path mismatch')
        p=choices[0]
        with p.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest!=expected:raise ValueError('APK hash mismatch')
        verified.append((p,Path(destination)))
    for src,dst in verified:
        dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)

if __name__=='__main__':
    changes=subprocess.check_output(['git','diff','--no-renames','--name-only',SOURCE,'HEAD'],text=True).splitlines()
    if not host_only(changes):raise SystemExit('Android/build inputs changed: frozen APK experiment refused')
    verified_copy(Path(sys.argv[1]))
    Path('render/apk-source.json').write_text(json.dumps(dict(android_source=SOURCE,artifact=14972612151,run=45504346259,files=SPEC,host_only_guard=True),indent=2))
