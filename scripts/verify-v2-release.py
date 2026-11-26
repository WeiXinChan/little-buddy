#!/usr/bin/env python3
"""Offline APK/backend release pairing; never connects or reads runtime credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

CONTRACT='v2-voice2-safety1-images2-volume1-management1-end1'

def compatible(apk, backend):
    if (type(apk.get('format')) is not int or type(backend.get('format')) is not int or
        any(type(apk.get(k)) is not int for k in ('wire','images_v','volume_v','management_v','local_help_v','session_end_v')) or
        apk.get('format')!=1 or backend.get('format')!=1 or
        apk.get('protocol_contract')!=CONTRACT or backend.get('protocol_contract')!=CONTRACT or
        [apk.get(k) for k in ('wire','images_v','volume_v','management_v','local_help_v','session_end_v')]!=[2,2,1,1,1,1] or
        not re.fullmatch('[a-f0-9]{40}',backend.get('source_sha','')) or
        not re.fullmatch('[a-f0-9]{64}',apk.get('resources_manifest_sha256',''))):
        raise ValueError('release_contract_mismatch')
    if backend.get('assets_manifest_sha256')!=apk['resources_manifest_sha256']:raise ValueError('release_resources_mismatch')
    entry=backend.get('files',{}).get('assets/v2-default/manifest.json',{})
    if entry.get('sha256')!=apk['resources_manifest_sha256']:
        raise ValueError('release_resources_mismatch')

def inspect(apk, pin_init_diagnostics=False, private_device_preset=False):
    with zipfile.ZipFile(apk) as z:
        meta=json.loads(z.read('assets/v2-build.json'))
        is_private=meta.get('private_device_preset',False)
        if is_private != private_device_preset or ('assets/v2-device-preset.bin' in z.namelist()) != private_device_preset:
            raise ValueError('private_device_artifact_requires_explicit_local_mode')
        raw=z.read('assets/v2-source-inventory.json').rstrip(b'\n')
        if hashlib.sha256(raw).hexdigest()!=meta['source_content_sha256']:raise ValueError('source_inventory_mismatch')
        root=Path(__file__).resolve().parents[1]
        for path,receipt in json.loads(raw).items():
            candidate=Path(path)
            if candidate.is_absolute() or '..' in candidate.parts:raise ValueError('source_inventory_path')
            target=root/candidate
            if not target.resolve().is_relative_to(root.resolve()) or target.is_symlink() or not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=receipt['sha256']:
                raise ValueError('source_snapshot_mismatch')
        if hashlib.sha256(z.read('assets/v2-default/manifest.json')).hexdigest()!=meta['resources_manifest_sha256']:
            raise ValueError('apk_resources_mismatch')
        if any(value in json.dumps(meta) for value in ['/home/','/tmp/','Bearer ','PRIVATE KEY','password']):
            raise ValueError('private_build_metadata')
        if meta['application_id']!='com.littlebuddy.sim.v2' or meta['version_code']!=22 or meta['version_name']!=('2.0.0-rc8.pin.fix6.device1' if private_device_preset else '2.0.0-rc8.pin.fix2' if pin_init_diagnostics else '2.0.0-rc8'):
            raise ValueError('candidate_version_mismatch')
        if pin_init_diagnostics and meta.get("distribution")!=("private_registered_device" if private_device_preset else "pin_init_fix_candidate"): raise ValueError("diagnostic_identity_mismatch")
        return meta

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--apk',required=True);p.add_argument('--backend-manifest',required=True)
    p.add_argument("--pin-init-diagnostics",action="store_true")
    p.add_argument("--private-device-preset",action="store_true")
    args=p.parse_args();meta=inspect(args.apk,args.pin_init_diagnostics,args.private_device_preset);backend=json.loads(Path(args.backend_manifest).read_text())
    compatible(meta,backend)
    print(json.dumps(dict(pairing='static_compatible',build_id=meta['build_id'],backend_source=backend['source_sha'],
        protocol_contract=CONTRACT,apk_sha256=hashlib.sha256(Path(args.apk).read_bytes()).hexdigest()),sort_keys=True))
