#!/usr/bin/env python3
"""Deterministic public source inventory for the V2 candidate; no environment or credentials."""
import argparse
import importlib.util
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = 'v2-voice2-safety1-images2-volume1-management1-end1'
# RC9 is bound to the star-bunny correction; QA changes require an explicit reviewed pin update.
RC9_RESOURCES_MANIFEST='d649ac79bc5203373ff44ebdd547bdd16772663467a22115fa75f589bef91ea1'

_spec=importlib.util.spec_from_file_location('v2_release_snapshot',Path(__file__).with_name('v2-release-snapshot.py'))
_snapshot=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_snapshot)
selected=_snapshot.selected
source_inventory=_snapshot.source_inventory

def generate(output):
    config=json.loads((ROOT/'app/v2-release.json').read_text())
    assert set(config)=={'format','version_code','version_name','application_id','protocol_contract','source_base'}
    assert len(config['source_base'])==40 and all(c in '0123456789abcdef' for c in config['source_base'])
    assert config['format']==1 and config['version_code']==23 and config['version_name']=='2.0.0-rc9'
    assert config['application_id']=='com.littlebuddy.sim.v2' and config['protocol_contract']==CONTRACT
    resource_raw,pngs=_snapshot.resource_files(ROOT)
    manifest=hashlib.sha256(resource_raw).hexdigest()
    assert manifest==RC9_RESOURCES_MANIFEST, 'RC9 reviewed resource manifest required'
    inventory=source_inventory(ROOT)
    _snapshot.bind_resources(inventory,resource_raw,pngs)
    canonical=_snapshot.canonical(inventory)
    digest=hashlib.sha256(canonical).hexdigest()
    result=dict(config,build_id=f'v2-{config["version_code"]}-{digest[:16]}',source_content_sha256=digest,
                resources_manifest_sha256=manifest,wire=2,images_v=2,volume_v=1,management_v=1,local_help_v=1,session_end_v=1,
                feedback_protocol="feedback-v1",min_sdk=26,target_sdk=36,abi=['arm64-v8a'],distribution='internal_debug_candidate')
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    (output/'v2-build.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    (output/'v2-source-inventory.json').write_bytes(canonical+b'\n')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output',required=True)
    args=parser.parse_args(); print(json.dumps(generate(args.output),sort_keys=True))
