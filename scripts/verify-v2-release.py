#!/usr/bin/env python3
"""Offline APK/backend release pairing; never connects or reads runtime credentials."""
import argparse
import importlib.util
import hashlib
import json
from pathlib import Path
import re
import zipfile

CONTRACT='v2-voice2-safety1-images2-volume1-management1-end1'
# RC9 is bound to the star-bunny correction; QA changes require an explicit reviewed pin update.
RC9_RESOURCES_MANIFEST='d649ac79bc5203373ff44ebdd547bdd16772663467a22115fa75f589bef91ea1'

_spec=importlib.util.spec_from_file_location('v2_release_snapshot',Path(__file__).with_name('v2-release-snapshot.py'))
_snapshot=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_snapshot)

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
        names=z.namelist()
        if len(names)!=len(set(names)):raise ValueError('duplicate_zip_entry')
        meta=json.loads(z.read('assets/v2-build.json'))
        if any(value in json.dumps(meta) for value in ['/home/','/tmp/','Bearer ','PRIVATE KEY','password']):
            raise ValueError('private_build_metadata')
        if (type(meta.get('private_device_preset')) is not bool or type(meta.get('diagnostics_enabled')) is not bool or
            meta['private_device_preset'] != private_device_preset or meta['diagnostics_enabled'] != pin_init_diagnostics or
            ('assets/v2-device-preset.bin' in names) != private_device_preset):
            raise ValueError('explicit_build_mode_mismatch')
        expected_name='2.0.0-rc9.local1' + ('.integrated1.device1' if private_device_preset else '')
        if meta['application_id']!='com.littlebuddy.sim.v2' or meta['version_code']!=26 or meta['version_name']!=expected_name:
            raise ValueError('candidate_version_mismatch')
        if meta['resources_manifest_sha256']!=RC9_RESOURCES_MANIFEST:
            raise ValueError('candidate_resources_mismatch')
        raw=z.read('assets/v2-source-inventory.json').rstrip(b'\n')
        if hashlib.sha256(raw).hexdigest()!=meta['source_content_sha256']:raise ValueError('source_inventory_mismatch')
        claimed=json.loads(raw)
        root=Path(__file__).resolve().parents[1]
        try:
            trusted=_snapshot.source_inventory(root)
            resource_raw,pngs=_snapshot.resource_files(root)
            _snapshot.bind_resources(trusted,resource_raw,pngs)
        except (AssertionError,OSError,ValueError) as error:raise ValueError('source_snapshot_mismatch') from error
        config=json.loads((root/'app/v2-release.json').read_bytes())
        if private_device_preset: config['version_name'] += '.integrated1.device1'
        if any(meta.get(key)!=value for key,value in config.items()):raise ValueError('candidate_config_mismatch')
        expected_distribution='private_registered_device' if private_device_preset else 'internal_debug_candidate'
        if meta.get('distribution')!=expected_distribution:raise ValueError('explicit_build_mode_mismatch')
        if not isinstance(claimed,dict) or set(claimed)!=set(trusted):raise ValueError('source_inventory_set_mismatch')
        for path,receipt in claimed.items():
            if (not isinstance(receipt,dict) or set(receipt)!={'sha256','size'} or
                type(receipt['size']) is not int or receipt!=trusted[path]):
                raise ValueError('source_snapshot_mismatch')
        canonical=_snapshot.canonical(trusted);digest=hashlib.sha256(canonical).hexdigest()
        if raw!=canonical or digest!=meta['source_content_sha256']:raise ValueError('source_inventory_mismatch')
        if meta['build_id']!='v2-26-'+digest[:16]:raise ValueError('source_build_id_mismatch')
        if hashlib.sha256(resource_raw).hexdigest()!=RC9_RESOURCES_MANIFEST:raise ValueError('candidate_resources_mismatch')
        if z.read('assets/v2-default/manifest.json')!=resource_raw:raise ValueError('apk_resources_mismatch')
        expected=set(pngs)|{'assets/v2-default/manifest.json'}
        actual={name for name in names if name.startswith('assets/v2-default/') and not name.endswith('/')}
        if actual!=expected:raise ValueError('apk_resource_set_mismatch')
        for name,data in pngs.items():
            if z.read(name)!=data:raise ValueError('apk_resource_payload_mismatch')
        return meta

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--apk',required=True);p.add_argument('--backend-manifest',required=True)
    p.add_argument('--pin-init-diagnostics',action='store_true')
    p.add_argument('--private-device-preset',action='store_true')
    args=p.parse_args();meta=inspect(args.apk,args.pin_init_diagnostics,args.private_device_preset);backend=json.loads(Path(args.backend_manifest).read_text())
    compatible(meta,backend)
    print(json.dumps(dict(pairing='static_compatible',build_id=meta['build_id'],backend_source=backend['source_sha'],
        protocol_contract=CONTRACT,apk_sha256=hashlib.sha256(Path(args.apk).read_bytes()).hexdigest()),sort_keys=True))
