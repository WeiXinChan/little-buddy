#!/usr/bin/env python3
"""Verify the delivered APK contains exactly the approved 60 PNGs and unchanged manifest."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

root = Path(__file__).resolve().parents[1]
apk = Path(sys.argv[1])
manifest = (root / 'assets/v2-default/manifest.json').read_bytes()
entries = json.loads(manifest)
assert len(entries) == len({x['id'] for x in entries}) == 60
with zipfile.ZipFile(apk) as archive:
    assert archive.read('assets/v2-default/manifest.json') == manifest
    expected = {'assets/v2-default/manifest.json'}
    for item in entries:
        name = 'assets/v2-default/png/' + item['id'] + '.png'
        expected.add(name)
        data = archive.read(name)
        assert hashlib.sha256(data).hexdigest() == item['png_sha256'], name
        assert data[:8] == b'\x89PNG\r\n\x1a\n'
        assert int.from_bytes(data[16:20], 'big') == int.from_bytes(data[20:24], 'big') == 512
    assert {x for x in archive.namelist() if x.startswith('assets/v2-default/')} == expected
print('APK asset audit: 60/60 PNG hashes/dimensions; exact manifest; no source SVG/extra files')
print('APK SHA256:', hashlib.sha256(apk.read_bytes()).hexdigest())
