"""Explicit foreground synthetic systemd probe. No production unit/input access."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT=Path(__file__).resolve().parents[2]
BASE='ba7ad42596feb315cddb910d15baa53d0956f1e8'
PROBE=r'''
import importlib.util,json,os,stat,tempfile
from pathlib import Path
root=Path(os.environ['CREDENTIALS_DIRECTORY'])
spec=importlib.util.spec_from_file_location('fixture_files',root/'module.py')
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
parent=root.stat();entry=(root/'fixture').stat()
metadata=dict(euid=os.geteuid(),egid=os.getegid(),parent_uid=parent.st_uid,parent_gid=parent.st_gid,
    parent_mode=oct(stat.S_IMODE(parent.st_mode)),file_uid=entry.st_uid,file_gid=entry.st_gid,
    file_mode=oct(stat.S_IMODE(entry.st_mode)),nlink=entry.st_nlink,
    parent_symlink=root.is_symlink(),file_symlink=(root/'fixture').is_symlink(),
    mountpoint=os.path.ismount(root),readonly=bool(os.statvfs(root).f_flag&os.ST_RDONLY))
try:
    value=f.read_checked(root/'fixture','synthetic')
    assert len(value)==64
    del value
    metadata.update(result='accepted',credential_content_printed=False)
    code=0
except f.ConfigurationError as error:
    metadata.update(result='rejected',code=str(error),credential_content_printed=False)
    code=23
print(json.dumps(metadata),flush=True)
raise SystemExit(code)
'''


def run_probe(source,label):
    with tempfile.TemporaryDirectory(prefix='wali-credential-fixture-') as temporary:
        root=Path(temporary);(root/'module.py').write_text(source);(root/'module.py').chmod(0o600)
        (root/'fixture').write_text(os.urandom(32).hex());(root/'fixture').chmod(0o600)
        unit='wali-credential-'+uuid.uuid4().hex
        command=['sudo','-n','systemd-run','--unit='+unit,'--wait','--pipe','--collect',
            '--property=DynamicUser=yes','--property=ProtectSystem=strict','--property=ProtectHome=yes',
            '--property=PrivateTmp=yes','--property=RuntimeMaxSec=15','--property=TimeoutStopSec=3',
            '--property=LoadCredential=module.py:'+str(root/'module.py'),
            '--property=LoadCredential=fixture:'+str(root/'fixture'),'/usr/bin/python3','-B','-c',PROBE]
        result=subprocess.run(command,capture_output=True,text=True,timeout=25)
        records=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
        if len(records)!=1:raise RuntimeError('synthetic_namespace_probe_no_result')
        report=dict(label=label,exit=result.returncode,metadata=records[0],
                    transient_unit=unit+'.service',systemd_output=result.stderr.strip(),
                    production_unit_touched=False,production_inputs_read=False)
        return report


if __name__=='__main__':
    destination=ROOT/'docs/testing/v2/systemd-credentials';destination.mkdir(parents=True,exist_ok=True)
    old=subprocess.check_output(['git','show',BASE+':backend/v2/files.py'],cwd=ROOT,text=True)
    before=run_probe(old,'original_head_reproduction')
    (destination/'original-namespace.json').write_text(json.dumps(before,indent=2)+'\n')
    print(json.dumps(before))
    if before['metadata']['result']!='rejected':raise SystemExit('original_negative_not_reproduced')
    after=run_probe((ROOT/'backend/v2/files.py').read_text(),'fixed_head')
    (destination/'fixed-namespace.json').write_text(json.dumps(after,indent=2)+'\n')
    print(json.dumps(after))
    if after['exit']!=0 or after['metadata']['result']!='accepted':raise SystemExit('fixed_namespace_failed')
