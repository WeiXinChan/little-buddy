#!/usr/bin/env python3
"""Deterministic public source inventory for the V2 candidate; no environment or credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = 'v2-voice2-safety1-images2-volume1-management1-end1'

def selected(path):
    return path.startswith(('app/src/main/', 'app/src/debug/', 'app/src/v2Debug/', 'app/libs/', 'gradle/wrapper/', 'assets/v2-default/')) or path in {
        'app/build.gradle.kts','app/v2-release.json','settings.gradle.kts','gradle.properties','gradlew','scripts/v2-build-metadata.py'}

def generate(output, pin_init_diagnostics=False, private_device_preset=False):
    config=json.loads((ROOT/'app/v2-release.json').read_text())
    assert set(config)=={'format','version_code','version_name','application_id','protocol_contract','source_base'}
    assert len(config['source_base'])==40 and all(c in '0123456789abcdef' for c in config['source_base'])
    assert config['format']==1 and config['version_code']==22 and config['version_name']=='2.0.0-rc8'
    assert config['application_id']=='com.littlebuddy.sim.v2' and config['protocol_contract']==CONTRACT
    assert not private_device_preset or pin_init_diagnostics
    if pin_init_diagnostics: config['version_name']='2.0.0-rc8.pin.fix2'
    if private_device_preset: config['version_name']='2.0.0-rc8.pin.fix6.device1'
    paths=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    paths=sorted(p for p in paths if p and selected(p))
    inventory={}
    for path in paths:
        file=ROOT/path
        assert not file.is_symlink() and file.is_file()
        public_transport = {'app/src/v2Debug/assets/v2-transport/ca.pem': 'ef47caf47e3d66b428d51a8d15c0c5960646af540c294caed37f7fcde3febe98', 'app/src/v2Debug/assets/v2-transport/ssh.properties': 'df09fed1f81baf30cb6abfa6a5edc32461d692b53f852e065f78ec35107aa1b2'}
        if path in public_transport: assert hashlib.sha256(file.read_bytes()).hexdigest()==public_transport[path]
        else: assert file.suffix not in {'.pem','.key','.jks','.keystore'}
        assert file.suffix!='.properties' or path in {'gradle.properties','gradle/wrapper/gradle-wrapper.properties'} or path in public_transport
        raw=file.read_bytes(); inventory[path]={'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
    # Unexpected local assets must not enter an APK without being inventoried/reviewed.
    for directory in ['app/src/main','app/src/debug','app/src/v2Debug','app/libs','assets/v2-default']:
        for file in (ROOT/directory).rglob('*'):
            if file.is_file(): assert file.relative_to(ROOT).as_posix() in inventory
    canonical=json.dumps(inventory,sort_keys=True,separators=(',',':')).encode()
    digest=hashlib.sha256(canonical).hexdigest()
    manifest=hashlib.sha256((ROOT/'assets/v2-default/manifest.json').read_bytes()).hexdigest()
    result=dict(config,build_id=f'v2-{config["version_code"]}-{digest[:16]}',source_content_sha256=digest,
                resources_manifest_sha256=manifest,wire=2,images_v=2,volume_v=1,management_v=1,local_help_v=1,session_end_v=1,
                private_device_preset=private_device_preset,feedback_protocol="feedback-v1",min_sdk=26,target_sdk=36,abi=['arm64-v8a'],distribution='private_registered_device' if private_device_preset else 'pin_init_fix_candidate' if pin_init_diagnostics else 'internal_debug_candidate')
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    (output/'v2-build.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    (output/'v2-source-inventory.json').write_bytes(canonical+b'\n')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output',required=True)
    parser.add_argument('--pin-init-diagnostics',action='store_true')
    parser.add_argument('--private-device-preset',action='store_true')
    args=parser.parse_args(); print(json.dumps(generate(args.output,args.pin_init_diagnostics,args.private_device_preset),sort_keys=True))
