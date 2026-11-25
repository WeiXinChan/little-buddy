#!/usr/bin/env python3
"""Inspect the built V2 manifest/DEX and actual compiled entry calls. This is not OS execution."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
import zipfile

p = argparse.ArgumentParser()
p.add_argument('--sdk', type=Path, required=True)
p.add_argument('--apk', type=Path, required=True)
p.add_argument('--manifest', type=Path, required=True)
p.add_argument('--classes', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
ns = '{http://schemas.android.com/apk/res/android}'
root = ET.parse(a.manifest).getroot()
app = root.find('application')
assert app.get(ns + 'name') == 'com.littlebuddy.v2.feedback.FeedbackApplication'
assert app.get(ns + 'process') is None
service = next(s for s in app.findall('service') if s.get(ns + 'name') == 'com.littlebuddy.v2.feedback.FeedbackSweepService')
assert service.get(ns + 'permission') == 'android.permission.BIND_JOB_SERVICE'
assert service.get(ns + 'process') is None
assert any(x.get(ns + 'name') == 'android.permission.RECEIVE_BOOT_COMPLETED' for x in root.findall('uses-permission'))
launchers = [x.get(ns + 'name') for x in app.findall('activity') if any(
    c.get(ns + 'name') == 'android.intent.category.LAUNCHER' for c in x.findall('intent-filter/category'))]
assert launchers == ['com.littlebuddy.V2VoiceActivity']

def call(command):
    return subprocess.check_output([str(x) for x in command], text=True, stderr=subprocess.STDOUT)

tools = a.sdk / 'build-tools/35.0.0'
manifest_dump = call([tools / 'aapt2', 'dump', 'xmltree', a.apk, '--file', 'AndroidManifest.xml'])
assert 'com.littlebuddy.v2.feedback.FeedbackApplication' in manifest_dump
assert 'android.permission.BIND_JOB_SERVICE' in manifest_dump
signing = call([tools / 'apksigner', 'verify', '--print-certs', a.apk])
entries = {}
for name, expected in [('FeedbackApplication', 'AndroidFeedbackRuntime.start'),
                       ('AndroidFeedbackRuntime', 'FeedbackMaintenance.start'),
                       ('FeedbackSweepService', 'FeedbackJobRuns.start')]:
    text = call(['javap', '-c', '-p', '-classpath', a.classes, 'com.littlebuddy.v2.feedback.' + name])
    assert expected in text
    entries[name] = text
with zipfile.ZipFile(a.apk) as z:
    assert any(b'Lcom/littlebuddy/v2/feedback/FeedbackApplication;' in z.read(n)
               for n in z.namelist() if n.endswith('.dex'))
report = {'apk_sha256': hashlib.sha256(a.apk.read_bytes()).hexdigest(), 'apk_bytes': a.apk.stat().st_size,
          'merged_manifest_sha256': hashlib.sha256(a.manifest.read_bytes()).hexdigest(),
          'launchers': launchers, 'signing': signing, 'entry_bytecode': entries,
          'scope': 'built manifest/DEX/signature and compiled callsites; no install/Android OS execution'}
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({k: report[k] for k in ['apk_sha256', 'apk_bytes', 'launchers', 'scope']}))
