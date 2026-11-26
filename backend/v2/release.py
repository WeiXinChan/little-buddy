"""Reproducible source release package and inventory verification, no deployment."""
import argparse
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
from backend.v2.preflight import CONTRACT,MODELS
from backend.v2.models import model_policy


def selected(path):
    return (path in {'backend/dashscope.py','backend/voice.py','backend/timing.py','backend/requirements-v2.lock'} or
            path.startswith('backend/v2/') and path.endswith('.py') or
            path.startswith('backend/deploy/v2-') or
            path in {'docs/testing/v2/release-ready/runbook.md','docs/testing/v2/release-ready/resources.md',
                     'docs/testing/v2/release-ready/handshake.md',
                     'docs/testing/v2/management-v1.md','docs/testing/v2/images-v1/protocol.md',
                     'docs/testing/v2/r88-01/protocol.md'} or
            path in {'assets/v2-default/manifest.json','assets/v2-default/character-identities.json'} or
            path.startswith('assets/v2-default/png/') and path.endswith('.png'))


def package(ref,output):
    if not re.fullmatch('[a-f0-9]{40}',ref):raise ValueError('release_ref_invalid')
    paths=subprocess.check_output(['git','ls-tree','-r','--name-only',ref],text=True).splitlines()
    files={p:subprocess.check_output(['git','show',ref+':'+p]) for p in paths if selected(p)}
    inventory={p:dict(sha256=sha256(raw).hexdigest(),size=len(raw)) for p,raw in files.items()}
    if 'backend/v2/live.py' not in files or 'backend/requirements-v2.lock' not in files:
        raise ValueError('release_source_incomplete')
    if files.get('backend/v2/models.py')!=Path(__file__).with_name('models.py').read_bytes():
        raise ValueError('release_source_model_mismatch')
    metadata=dict(format=1,source_sha=ref,protocol_contract=CONTRACT,models=MODELS,model_policy=model_policy(),region='cn-beijing',
                  assets_manifest_sha256=sha256(files['assets/v2-default/manifest.json']).hexdigest(),
                  python='>=3.11',bind='127.0.0.1',path='/v2/voice',files=inventory,
                  ownership_issuer='not_included',credentials='external_only')
    files['release-manifest.json']=(json.dumps(metadata,sort_keys=True,indent=2)+'\n').encode()
    with open(output,'xb') as target,gzip.GzipFile(fileobj=target,mode='wb',filename='',mtime=0) as zipped:
        with tarfile.open(fileobj=zipped,mode='w') as archive:
            for path,raw in sorted(files.items()):
                member=tarfile.TarInfo(path);member.size=len(raw);member.mode=0o644;member.mtime=0
                archive.addfile(member,io.BytesIO(raw))
    return sha256(Path(output).read_bytes()).hexdigest()


def verify(root,expected):
    root=Path(root)
    if expected=='selected':expected=root.resolve().name
    if not re.fullmatch('[a-f0-9]{40}',expected):raise ValueError('release_ref_invalid')
    if root.is_symlink():raise ValueError('release_directory_invalid')
    manifest=root/'release-manifest.json'
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size>1024*1024:
        raise ValueError('release_manifest_invalid')
    metadata=json.loads(manifest.read_text())
    if (metadata.get('format')!=1 or metadata.get('source_sha')!=expected or
        metadata.get('protocol_contract')!=CONTRACT):raise ValueError('release_version_mismatch')
    if metadata.get('models')!=MODELS or metadata.get('model_policy')!=model_policy():
        raise ValueError('release_model_policy_mismatch')
    inventory=metadata['files']
    if not isinstance(inventory,dict) or len(inventory)>1000:raise ValueError('release_inventory_invalid')
    if (not isinstance(metadata.get('assets_manifest_sha256'),str) or
        not re.fullmatch('[a-f0-9]{64}',metadata['assets_manifest_sha256']) or
        metadata['assets_manifest_sha256']!=inventory.get('assets/v2-default/manifest.json',{}).get('sha256')):
        raise ValueError('release_assets_version_mismatch')
    for path,receipt in inventory.items():
        if not selected(path) or '..' in Path(path).parts or Path(path).is_absolute():raise ValueError('release_path_invalid')
        target=root/path
        if any(parent.is_symlink() for parent in [target,*target.parents] if parent!=root.parent):
            raise ValueError('release_symlink_invalid')
        if (type(receipt['size']) is not int or not 0<=receipt['size']<=8*1024*1024 or
            not target.is_file() or target.stat().st_size!=receipt['size']):raise ValueError('release_integrity_failed')
        raw=target.read_bytes()
        if len(raw)!=receipt['size'] or sha256(raw).hexdigest()!=receipt['sha256']:
            raise ValueError('release_integrity_failed')
    actual={p.relative_to(root).as_posix() for p in root.rglob('*')
            if p.is_file() and '.venv' not in p.relative_to(root).parts and p!=manifest}
    if actual!=set(inventory):raise ValueError('release_extra_or_missing_files')
    return metadata


def cli():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='action',required=True)
    pack=sub.add_parser('package');pack.add_argument('--ref',required=True);pack.add_argument('--output',required=True)
    check=sub.add_parser('verify');check.add_argument('--directory',required=True);check.add_argument('--ref',required=True)
    args=parser.parse_args()
    try:
        if args.action=='package':print(json.dumps(dict(sha256=package(args.ref,args.output))))
        else:verify(args.directory,args.ref);print('{"release":"verified"}')
    except Exception:
        print('{"release":"rejected"}');return 2
    return 0


if __name__=='__main__':raise SystemExit(cli())
