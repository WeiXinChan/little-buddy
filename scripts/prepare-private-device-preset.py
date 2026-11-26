#!/usr/bin/env python3
"""Explicit local-only build preparation. Never prints credentials or embeds them in source."""
import argparse, os, re, struct, sys
from pathlib import Path

SOURCE = Path('/etc/little-buddy-v2/v2-device-token')
ROOT = Path(__file__).resolve().parents[1]

def prepare(owner):
    # Read only this user-authorized issued credential file, not environment/model/V1 credentials.
    raw = SOURCE.read_bytes().rstrip(b'\r\n')
    if not re.fullmatch(rb'[a-zA-Z0-9]{32,256}', raw): raise ValueError('invalid issued credential')
    directory = ROOT/'.private-device'
    if directory.is_symlink(): raise ValueError('invalid destination')
    directory.mkdir(mode=0o700,exist_ok=True)
    os.chmod(directory,0o700)
    parts = [b'LBV2P1', b'v2-device-oppo', b'wss://127.0.0.1:19483/v2/voice', raw]
    payload = b''.join(struct.pack('>H',len(p))+p for p in parts)
    target=directory/'preset.bin'
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'wb',closefd=False) as f:f.write(payload);f.flush();os.fsync(f.fileno())
        if owner is not None:os.fchown(fd,owner,-1);os.chown(directory,owner,-1)
    finally:os.close(fd)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--owner-uid',type=int);a=p.parse_args()
    try:prepare(a.owner_uid)
    except Exception:
        print('Private preset preparation failed; credential not displayed.',file=sys.stderr);sys.exit(1)
    print('Private preset prepared; contents not displayed.')
