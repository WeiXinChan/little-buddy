#!/usr/bin/env python3
"""Remove unused legacy PCM fixtures and old signatures from the deliverable TEST APK only.
Run zipalign/apksigner afterwards with the already-authorized test signing key. No target APK edits.
"""
import argparse,zipfile,json,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('input');p.add_argument('output');a=p.parse_args()
assert Path(a.input).resolve()!=Path(a.output).resolve()
removed=[];kept={}
with zipfile.ZipFile(a.input) as src,zipfile.ZipFile(a.output,'w') as dst:
 for item in src.infolist():
  name=item.filename
  legacy=name.startswith('assets/wake/') and name.endswith('.pcm')
  signature=name.startswith('META-INF/') and (name.endswith(('.RSA','.DSA','.EC','.SF')) or name=='META-INF/MANIFEST.MF')
  if legacy or signature:removed.append(name);continue
  assert not name.lower().endswith(('.pcm','.wav','.mp3','.m4a','.ogg')),'unexpected audio entry: '+name
  data=src.read(name);dst.writestr(item,data);kept[name]=hashlib.sha256(data).hexdigest()
assert removed and any(x.endswith('.pcm') for x in removed)
print(json.dumps({'removed':removed,'retained_entries':len(kept),'classes_and_manifest_sha256':{k:v for k,v in kept.items() if k.endswith('.dex') or k=='AndroidManifest.xml'}},sort_keys=True,indent=2))
