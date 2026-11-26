#!/usr/bin/env python3
"""Offline ZIP policy tests only; do not claim these dummy archives install or run JNI."""
from pathlib import Path
import subprocess,tempfile,zipfile,json,hashlib,warnings
root=Path(__file__).resolve().parents[3]
policy=root/'app/src/androidTest/strip-probe-fixtures.py'
fixtures={name:(root/'app/src/androidTest'/name).read_bytes() for _,name in
          (line.split() for line in (root/'scripts/wake-fixtures.sha256').read_text().splitlines())}
with tempfile.TemporaryDirectory(dir=root,prefix='wake-packaging-tests-') as directory:
 d=Path(directory)
 def check(label,entries,known=True,valid=False,duplicate=False):
  source=d/(label+'.zip');output=d/(label+'-out.zip')
  with warnings.catch_warnings():
   warnings.simplefilter('ignore',UserWarning)
   with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED) as z:
    for name,data in entries.items():z.writestr(name,data)
    z.writestr('resources.arsc',b'POLICY_TEST_NOT_AN_APK')
    if duplicate:z.writestr(next(iter(fixtures)),next(iter(fixtures.values())))
  cmd=['python3',str(policy),str(source),str(output)]+(['--known-wake-fixtures'] if known else [])
  result=subprocess.run(cmd,text=True,capture_output=True)
  assert (result.returncode==0)==valid,(label,result.stderr)
  if valid:
   json.loads(result.stdout)
   with zipfile.ZipFile(output) as z:
    audio={n:z.read(n) for n in z.namelist() if n.endswith('.pcm')}
    assert audio==(fixtures if known else {}),label
    assert z.getinfo('resources.arsc').compress_type==zipfile.ZIP_STORED
  print(label+': PASS')
 check('known_exact_keep',fixtures,valid=True)
 check('timestamp_default_no_audio',fixtures,known=False,valid=True)
 changed=dict(fixtures);name=next(iter(changed));changed[name]=changed[name][:-2]+b'\x01\x02'
 check('mutated_fixture',changed)
 check('unknown_pcm',dict(fixtures,**{'assets/wake/unknown.pcm':b'BAD'}))
 check('hidden_asset',dict(fixtures,**{'assets/unknown.bin':b'BAD'}))
 check('missing_fixture',{k:v for k,v in fixtures.items() if k!=name})
 check('duplicate_entry',fixtures,duplicate=True)
 check('outside_asset_audio',dict(fixtures,**{'res/raw/unknown.wav':b'BAD'}))
print('PACKAGING_POLICY: 8/8 passed (ZIP policy only; no device/install/JNI)')
