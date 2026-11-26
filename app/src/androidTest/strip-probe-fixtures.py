#!/usr/bin/env python3
"""Remove unused legacy PCM fixtures and old signatures from the deliverable TEST APK only.
Run zipalign/apksigner afterwards with the already-authorized test signing key. No target APK edits.
"""
import argparse,zipfile,json,hashlib,copy
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('input');p.add_argument('output');p.add_argument('--known-wake-fixtures',action='store_true');a=p.parse_args()
assert Path(a.input).resolve()!=Path(a.output).resolve()
expected={}
if a.known_wake_fixtures:
 for line in (Path(__file__).resolve().parents[3]/'scripts/wake-fixtures.sha256').read_text().splitlines():
  digest,name=line.split();expected[name]=digest
 assert len(expected)==3 and set(expected)=={'assets/wake/command-alone.pcm','assets/wake/gap-120.pcm','assets/wake/wake.pcm'}
removed=[];kept={};seen={}

with zipfile.ZipFile(a.input) as src,zipfile.ZipFile(a.output,'w') as dst:
 assert len(src.namelist())==len(set(src.namelist())),'duplicate ZIP entry'
 for item in src.infolist():
  name=item.filename
  legacy=name.startswith('assets/wake/') and name.endswith('.pcm')
  signature=name.startswith('META-INF/') and (name.endswith(('.RSA','.DSA','.EC','.SF')) or name=='META-INF/MANIFEST.MF')
  if a.known_wake_fixtures and name.startswith('assets/') and not name.endswith('/'):
   assert name in expected,'unexpected probe asset: '+name
  audio=name.lower().endswith(('.pcm','.wav','.mp3','.m4a','.ogg','.flac','.aac','.aiff','.opus','.wma','.amr','.aif','.au','.caf','.mp4','.webm'))
  if a.known_wake_fixtures and audio:
   assert name in expected,'unexpected audio entry: '+name
   seen[name]=hashlib.sha256(src.read(name)).hexdigest()
   assert seen[name]==expected[name],'wake fixture hash mismatch: '+name
  if (legacy and not a.known_wake_fixtures) or signature:removed.append(name);continue
  assert not audio or (a.known_wake_fixtures and name in expected),'unexpected audio entry: '+name
  # extractNativeLibs=false and Android's resource loader require stored/aligned entries.
  # Preserve entry CONTENT exactly; zipalign supplies alignment after this filtering step.
  data=src.read(name)
  output=copy.copy(item) # Do not mutate the source ZipInfo before decompressing its payload.
  if name=='resources.arsc' or (name.startswith('lib/') and name.endswith('.so')):
   output.compress_type=zipfile.ZIP_STORED
  dst.writestr(output,data);kept[name]=hashlib.sha256(data).hexdigest()
if a.known_wake_fixtures:assert seen==expected,'missing known wake fixture'
else:assert removed and any(x.endswith('.pcm') for x in removed)
print(json.dumps({'known_wake_fixtures':seen,'removed':removed,'retained_entries':len(kept),'classes_and_manifest_sha256':{k:v for k,v in kept.items() if k.endswith('.dex') or k=='AndroidManifest.xml'}},sort_keys=True,indent=2))
