#!/usr/bin/env python3
"""Dedicated V2 namespace only. No journal paths, wildcard, or global vacuum API.

Install outside current/releases so rollback cannot remove this safety gate.
`check` reads configuration/effective route only; `sweep` requires root and uses
fixed journalctl commands. Successful command exit isn't an all-copies receipt.
"""
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import time

NAMESPACE='little-buddy-v2'
CONFIG=Path('/etc/systemd/journald@little-buddy-v2.conf')
EXPECTED=dict(Storage='persistent',ForwardToSyslog='no',ForwardToKMsg='no',
              ForwardToConsole='no',ForwardToWall='no',MaxRetentionSec='6day',
              MaxFileSec='1h',SystemMaxUse='32M',RuntimeMaxUse='8M',
              SystemMaxFileSize='4M',RuntimeMaxFileSize='1M',SystemMaxFiles='32',RuntimeMaxFiles='8')
DAY=86400

class Rejected(Exception):
    def __init__(self,code):self.code=code;super().__init__(code)

def execute(command):
    # No inherited pager/grep/namespace selectors, no shell, no child body logs.
    result=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                          timeout=5,check=True,env={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C','SYSTEMD_PAGER':''})
    if len(result.stdout)>65536:raise Rejected('metadata_invalid')
    return result.stdout.decode('utf-8',errors='strict')

def checked_file(path):
    for parent in reversed(path.parents):
        info=parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or stat.S_IMODE(info.st_mode)&0o022:raise Rejected('policy_unsafe')
    info=path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1 or
            stat.S_IMODE(info.st_mode)!=0o644 or info.st_size>65536):raise Rejected('policy_unsafe')


def check():
    checked_file(CONFIG)
    effective=execute(['/usr/bin/systemd-analyze','cat-config','systemd/journald@'+NAMESPACE+'.conf'])
    section=None;values={}
    for line in effective.splitlines():
        line=line.strip()
        if not line or line.startswith(('#',';')):continue
        if line.startswith('[') and line.endswith(']'):section=line[1:-1];continue
        if section!='Journal' or '=' not in line:raise Rejected('policy_invalid')
        key,value=map(str.strip,line.split('=',1));values[key]=value
    # Refuse unreviewed additional options too, including future forwarding flags.
    if values!=EXPECTED:raise Rejected('policy_invalid')
    route=execute(['/usr/bin/systemctl','show','little-buddy-v2.service','--no-pager',
                   '--property=LogNamespace,SyslogIdentifier,StandardOutput,StandardError,Requires,After'])
    fields=dict(line.split('=',1) for line in route.splitlines() if '=' in line)
    if any(fields.get(k)!=v for k,v in dict(LogNamespace=NAMESPACE,SyslogIdentifier=NAMESPACE,
              StandardOutput='journal',StandardError='journal').items()):raise Rejected('route_invalid')
    if not {'little-buddy-v2-log-retention.service','little-buddy-v2-log-retention.timer'}<=set(fields.get('Requires','').split()):raise Rejected('route_invalid')
    if 'little-buddy-v2-log-retention.service' not in fields.get('After','').split():raise Rejected('route_invalid')


def sweep():
    check()
    if os.geteuid()!=0:raise Rejected('root_required')
    now=time.time() # never stored/renewed from current activity; original entry timestamps remain authoritative
    if not 0<now<10**11:raise Rejected('clock_invalid')
    try:
        execute(['/usr/bin/journalctl','--namespace='+NAMESPACE,'--rotate','--vacuum-time=6d','--vacuum-size=32M','--quiet'])
    except Exception:raise Rejected('sweep_failed') from None
    checked=time.time()
    if not now<=checked<10**11:raise Rejected('clock_invalid')
    now=checked
    # Query a conservative horizon so I/O cannot turn a clean query stale.
    # Each command has a 5s timeout; reject if the 60s observation margin is spent.
    margin=60
    def timestamp(raw):
        lines=raw.splitlines()
        if len(lines)>1:raise ValueError()
        if not lines:return None
        value=json.loads(lines[0])
        if not set(value)<={'__REALTIME_TIMESTAMP','__CURSOR','__MONOTONIC_TIMESTAMP','_BOOT_ID','__SEQNUM','__SEQNUM_ID'} or not isinstance(value['__REALTIME_TIMESTAMP'],str) or not value['__REALTIME_TIMESTAMP'].isdigit():raise ValueError()
        result=int(value['__REALTIME_TIMESTAMP'])/1000000
        if result<=0 or result>now+60:raise ValueError()
        return result
    metadata=['/usr/bin/journalctl','--namespace='+NAMESPACE,'--no-pager','--quiet',
              '--output=json','--output-fields=__REALTIME_TIMESTAMP']
    try:
        cutoff=now-7*DAY+margin
        overdue=timestamp(execute(metadata+['--until=@'+format(cutoff,'.6f'),'--reverse','--lines=1']))
        oldest=timestamp(execute(metadata+['--lines=+1']))
    except Exception:raise Rejected('metadata_invalid') from None
    completed=time.time()
    if not now<=completed<10**11 or completed-now>=margin:raise Rejected('clock_invalid')
    if overdue is not None:
        if overdue>cutoff:raise Rejected('metadata_invalid')
        raise Rejected('retention_overdue' if overdue<=completed-7*DAY else 'retention_margin')
    if oldest is not None and oldest<=cutoff:
        raise Rejected('retention_overdue' if oldest<=completed-7*DAY else 'retention_margin')
    return dict(oldest_age_seconds=None if oldest is None else int(completed-oldest),
                namespace=NAMESPACE,all_copies_deleted=False,scope='future_v2_application_namespace_only')


def cli(argv=None):
    # Deliberately no --directory / --file / arbitrary namespace or command passthrough.
    class FixedParser(argparse.ArgumentParser):
        def error(self,message):raise Rejected('arguments_invalid')
    parser=FixedParser()
    parser.add_argument('action',choices=('check','sweep'))
    parser.add_argument('--namespace',choices=(NAMESPACE,),default=NAMESPACE)
    try:args=parser.parse_args(argv)
    except Rejected:
        print('{"v2_log_retention":"arguments_invalid"}');return 2
    except SystemExit as error:
        if error.code:print('{"v2_log_retention":"arguments_invalid"}')
        return 2 if error.code else 0
    try:
        result=sweep() if args.action=='sweep' else (check() or {})
        print(json.dumps(dict(v2_log_retention='sweep_checked' if args.action=='sweep' else 'config_checked',**result)))
        return 0
    except Rejected as error:
        print(json.dumps(dict(v2_log_retention=error.code)));return 2
    except Exception:
        print('{"v2_log_retention":"check_failed"}');return 2

if __name__=='__main__':raise SystemExit(cli())
