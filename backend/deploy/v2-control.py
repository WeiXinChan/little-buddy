#!/usr/bin/env python3
"""Root-reviewed V2-only stop/select/start/rollback. Default is a non-mutating plan."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import stat
import sys
import uuid

SERVICE='little-buddy-v2.service'
ROOT=Path('/opt/little-buddy-v2')
CONFIG=Path('/etc/little-buddy-v2')
STATE=Path('/var/lib/little-buddy-v2/feedback')
CONTRACT='v2-voice2-safety1-images2-volume1-management1-end1'


def run(command,*,cwd=None):
    subprocess.run(command,cwd=cwd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def checked_image_sources():
    # LoadCredential requires all three sources even when image.json disables
    # generation. Mirror that requirement without opening/logging their contents.
    directory=CONFIG.lstat()
    if (not stat.S_ISDIR(directory.st_mode) or stat.S_IMODE(directory.st_mode)!=0o700 or
        directory.st_uid not in {0,os.geteuid()}):raise ValueError()
    for name in ('image.json','dashscope-image-key','dashscope-review-key'):
        info=(CONFIG/name).lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600 or
            info.st_uid not in {0,os.geteuid()}):raise ValueError()


LOG_FILES={
    'v2-log-retention.py':Path('/opt/little-buddy-v2/log-policy/v2-log-retention.py'),
    'v2-journald.conf':Path('/etc/systemd/journald@little-buddy-v2.conf'),
    'v2-log-retention.service':Path('/etc/systemd/system/little-buddy-v2-log-retention.service'),
    'v2-log-retention.timer':Path('/etc/systemd/system/little-buddy-v2-log-retention.timer'),
    'v2-log-retention.dropin.conf':Path('/etc/systemd/system/little-buddy-v2.service.d/70-log-retention.conf'),
}

def checked_log_policy(target):
    # Stable overlay remains installed across select/rollback; old/mismatched
    # releases cannot silently remove or downgrade this policy.
    for name,installed in LOG_FILES.items():
        for parent in installed.parents:
            info=parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or stat.S_IMODE(info.st_mode)&0o022:raise ValueError()
        info=installed.lstat();source=target/'backend/deploy'/name
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1 or
            stat.S_IMODE(info.st_mode)!=0o644 or info.st_size>65536 or
            source.is_symlink() or installed.read_bytes()!=source.read_bytes()):raise ValueError()
    run(['/usr/bin/python3','-B',str(LOG_FILES['v2-log-retention.py']),'check','--namespace','little-buddy-v2'],cwd=target)


def checked_release(sha):
    if not re.fullmatch('[a-f0-9]{40}',sha or ''):raise ValueError()
    target=ROOT/'releases'/sha
    if target.is_symlink() or not (target/'.venv/bin/python').is_file():raise ValueError()
    python=str(target/'.venv/bin/python')
    run([python,'-B','-m','backend.v2.release','verify','--directory',str(target),'--ref',sha],cwd=target)
    checked_image_sources()
    checked_log_policy(target)
    run([python,'-B','-m','backend.v2.live','--check','--cert',str(CONFIG/'tls-certificate.pem'),
        '--key',str(CONFIG/'tls-private-key.pem'),'--ca-file',str(CONFIG/'trust-anchor.pem'),
        '--tls-name','127.0.0.1','--token-file',str(CONFIG/'v2-device-token'),
        '--device-scope',str(CONFIG/'device-scope.json'),'--service-env',str(CONFIG/'service.env'),
        '--credential-directory',str(CONFIG),'--image-config',str(CONFIG/'image.json'),
        '--feedback-database',str(STATE/'issues.sqlite'),'--port','19483','--apk-contract',CONTRACT],cwd=target)
    return target


def select(sha):
    temporary=ROOT/('.select-'+uuid.uuid4().hex)
    try:
        temporary.symlink_to('releases/'+sha)
        os.replace(temporary,ROOT/'current')
    finally:
        if temporary.is_symlink():temporary.unlink()


def cli(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['check','start','stop','rollback'])
    parser.add_argument('sha',nargs='?');parser.add_argument('--apply',action='store_true')
    args=parser.parse_args(argv)
    if args.action!='stop' and not re.fullmatch('[a-f0-9]{40}',args.sha or ''):
        print('{"v2_control":"release_sha_required"}');return 2
    if not args.apply:
        print(json.dumps(dict(v2_control='plan_only',action=args.action,release=args.sha,
                             service=SERVICE,changes=False)));return 0
    if os.geteuid()!=0:print('{"v2_control":"root_required"}');return 2
    try:
        if args.action=='stop':run(['systemctl','stop',SERVICE])
        else:
            checked_release(args.sha)
            if args.action=='check':print('{"v2_control":"preflight_pass"}');return 0
            # Validate before stopping; rollback never restores old credentials.
            run(['systemctl','stop',SERVICE]);select(args.sha)
            run(['systemctl','start',SERVICE]);run(['systemctl','is-active','--quiet',SERVICE])
        print('{"v2_control":"complete"}');return 0
    except Exception:
        print('{"v2_control":"failed_closed_operator_action_required"}');return 2


if __name__=='__main__':raise SystemExit(cli())
