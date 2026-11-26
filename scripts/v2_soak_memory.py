"""Preparation-only by default. No profiling on import or report analysis.

Future profile runs export the frozen source and use serial isolated children,
synthetic providers only, with the existing heavy.lock acquired nonblockingly.
RSS deltas / allocation locations aren't proof of a production leak.
"""
import argparse
import asyncio
from collections import Counter
from contextlib import contextmanager
import gc
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import weakref

SOURCE='3aa8902f93db2e2a83577a50f32edccf8d42cd50'
LOCK=Path('/var/lock/little-buddy/heavy.lock')
GROUPS=('runner','production_voice','production_session','production_memory','asyncio','measurement','serialization','other')

class Invalid(Exception):pass

def deep_size(value,limit=300000):
    """Reachable container estimate, not RSS ownership; shared identities once."""
    seen=set();todo=[value];total=0
    while todo:
        item=todo.pop();key=id(item)
        if key in seen:continue
        seen.add(key)
        if len(seen)>limit:raise Invalid('object_cap')
        total+=sys.getsizeof(item)
        if isinstance(item,dict):todo.extend(item.keys());todo.extend(item.values())
        elif isinstance(item,(list,tuple,set,frozenset)):todo.extend(item)
    return total

def analyze(path):
    path=Path(path)
    if path.stat().st_size>16*1024*1024:raise Invalid('report_size')
    raw=path.read_bytes();report=json.loads(raw)
    if report.get('cloud_enabled') is not False or report.get('device_executed') is not False or report.get('layer')!='synthetic_text_real_voicepeer_json_duplex_simulated_ack':raise Invalid('evidence_layer')
    observations=report.get('sampling',{}).get('observations')
    if type(observations) is not int or observations<0:raise Invalid('sample_count')
    samples=report['resource_samples'];attempts=report['attempts']
    if not isinstance(samples,list) or not isinstance(attempts,list) or len(samples)>4096 or len(attempts)>120:raise Invalid('report_shape')
    if any(type(row) is not dict for row in samples+attempts):raise Invalid('report_shape')
    bands=[]
    for index in range(6):
        rows=[r for r in samples if type(r.get('elapsed')) in (float,int) and min(5,max(0,int(r['elapsed']//600)))==index]
        rss=[r['backend_rss_bytes'] for r in rows if type(r.get('backend_rss_bytes')) is int]
        bands.append(dict(band=index,samples=len(rows),rss_first=rss[0] if rss else None,rss_last=rss[-1] if rss else None))
    rss=[r['backend_rss_bytes'] for r in samples if type(r.get('backend_rss_bytes')) is int]
    return dict(format=1,mode='existing_report_read_only',report_sha256=sha256(raw).hexdigest(),frozen_source=SOURCE,
                attempts=len(attempts),sample_rows=len(samples),sample_observations=observations,
                failures=sum(r.get('status') not in {'delivered','interrupted'} for r in attempts),
                rss_first=rss[0] if rss else None,rss_last=rss[-1] if rss else None,
                rss_delta=None if not rss else rss[-1]-rss[0],bands=bands,
                decoded_report_reachable_bytes=deep_size(report),size_scope='this_process_JSON_decode_not_original_heap',
                source_expected_owner_task_handles=2*len(attempts)+1,task_handle_count_kind='source_derived_not_measured',
                production_leak_confirmed=False,attribution='unknown',profile_executed=False,
                original_report_modified=False,cloud_calls=0,device_executed=False)

class WeakRegistry:
    def __init__(self):self.refs={};self.observations=0;self.created=Counter()
    def remember(self,kind,value):
        group=self.refs.setdefault(kind,{})
        key=id(value)
        if key in group and group[key]() is value:return
        if sum(map(len,self.refs.values()))>=8192:raise Invalid('weak_registry_cap')
        group[key]=weakref.ref(value);self.observations+=1;self.created[kind]+=1
    def counts(self):
        return {k:dict(observed=self.created[k],retained_weak_slots=len(refs),live=sum(ref() is not None for ref in refs.values())) for k,refs in self.refs.items()}
    def summaries(self):
        totals=Counter()
        for ref in self.refs.get('ownership',{}).values():
            obj=ref()
            if obj is not None:
                totals['owner_task_handles']+=len(obj.tasks)
                totals['owner_done_task_handles']+=sum(t.done() for t in obj.tasks)
                totals['owner_pending']+=len(obj.pending())
        for ref in self.refs.get('session',{}).values():
            obj=ref()
            if obj is not None:
                for name in ('public','private','recent','facts','source_archive','pending','game','secrets'):
                    totals['session_'+name+'_size']+=len(getattr(obj,name))
        return dict(totals) # only lengths, never values/locals/referrers

def category(filename):
    name=filename.replace('\\','/')
    if name.endswith('/v2_soak_memory.py'):return 'measurement'
    if name.endswith(('/v2_soak.py','/v2_multiturn_probe.py')):return 'runner'
    for suffix,group in (('/backend/v2/voice.py','production_voice'),('/backend/v2/session.py','production_session'),('/backend/v2/memory.py','production_memory')):
        if name.endswith(suffix):return group
    if '/asyncio/' in name:return 'asyncio'
    if '/json/' in name:return 'serialization'
    return 'other'

def allocation_groups(snapshot):
    result={key:dict(bytes=0,blocks=0) for key in GROUPS}
    for entry in snapshot.statistics('traceback'):
        # Allocation site, not an ownership/retainer claim. No filename/line/source output.
        group=category(entry.traceback[-1].filename)
        result[group]['bytes']+=entry.size;result[group]['blocks']+=entry.count
    return result

def rss():
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith('VmRSS:'):return int(line.split()[1])*1024
    return None

@contextmanager
def heavy_lock():
    parent=LOCK.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=0 or parent.st_gid!=0 or stat.S_IMODE(parent.st_mode)!=0o755:raise Invalid('lock_unsafe')
    fd=os.open(LOCK,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_gid!=0 or stat.S_IMODE(info.st_mode)!=0o644:raise Invalid('lock_unsafe')
        import fcntl
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise Invalid('lock_busy') from None
        yield fd
    finally:os.close(fd)

def check_worker_lock(fd):
    if type(fd) is not int or fd<0:raise Invalid('worker_lock_required')
    info=os.fstat(fd);expected=LOCK.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_gid!=0 or stat.S_IMODE(info.st_mode)!=0o644 or (info.st_dev,info.st_ino)!=(expected.st_dev,expected.st_ino):raise Invalid('worker_lock_invalid')
    import fcntl
    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise Invalid('lock_busy') from None

async def worker(arm,attempts,artifact):
    # Executed only in the exported frozen-source child, never by default CLI.
    sys.path.insert(0,str(Path.cwd()))
    from scripts import v2_soak as soak
    from unittest.mock import patch
    import tracemalloc
    registry=WeakRegistry();checkpoints=[];phases=[]
    duration=max(3.,attempts*.3);limits=soak.Limits(duration=duration,interval=.04,sample_interval=.1,
                                                  attempt_timeout=2,max_attempts=attempts)
    Backend,Owner,Collector=soak.BackendTransport,soak.BatchState,soak.ResourceCollector
    class ObservedBackend(Backend):
        def __init__(self,*a,**k):
            super().__init__(*a,**k)
            for name,value in (('transport',self),('peer',self.peer),('session',self.peer.session)):registry.remember(name,value)
        def start(self):
            super().start()
            for task in self.tasks:registry.remember('task',task)
    class ObservedOwner(Owner):
        def __init__(self):super().__init__();registry.remember('ownership',self)
        def track(self,task):super().track(task);registry.remember('task',task)
    class ObservedCollector(Collector):
        def __init__(self,*a,**k):super().__init__(*a,**k);registry.remember('collector',self)
        def record(self,phase):
            super().record(phase)
            peer=self.transport.peer
            for task,operation in peer.generation_scopes.items():
                registry.remember('task',task);registry.remember('operation',operation)
            for task in peer.retired_tasks:registry.remember('task',task)
            if phase=='attempt_finished':
                checkpoints.append(dict(index=len(checkpoints),sample_rows=len(self.rows),observations=self.seen,
                                        **registry.summaries()))
    gc.collect()
    traced=arm!='plain'
    if traced:tracemalloc.start(8)
    def point(label,report=None):
        row=dict(phase=label,rss_bytes=rss(),live=registry.counts(),counts=registry.summaries(),
                 trace_current=None,trace_peak=None,trace_metadata_bytes=None,allocation_groups=None)
        if traced:
            row['trace_current'],row['trace_peak']=tracemalloc.get_traced_memory()
            row['trace_metadata_bytes']=tracemalloc.get_tracemalloc_memory()
            snapshot=tracemalloc.take_snapshot();row['allocation_groups']=allocation_groups(snapshot);del snapshot
        # This accounting itself allocates, after the RSS/trace snapshot; same
        # weak observer and output path in both actual-workload arms.
        row['report_reachable_bytes']=None if report is None else deep_size(report)
        phases.append(row)
    point('baseline_after_import_gc')
    if arm=='idle':
        await asyncio.sleep(duration)
        report=dict(attempts=[],resource_samples=[],cleanup=dict(confirmed=True,pending_tasks=0))
    else:
        with patch.multiple(soak,BackendTransport=ObservedBackend,BatchState=ObservedOwner,ResourceCollector=ObservedCollector):
            report=await soak.run_soak(limits)
    point('returned_report_held',report)
    # Preserve complete report BEFORE releasing references. Never reset its
    # samples/attempt ledger or prune production task sets for a nicer slope.
    with open(artifact,'x') as out:json.dump(report,out,sort_keys=True)
    digest=sha256()
    with open(artifact,'rb') as source:
        for chunk in iter(lambda:source.read(65536),b''):digest.update(chunk)
    ledger=report['attempts']
    signature=sha256(json.dumps([(r.get('index'),r.get('scenario'),r.get('injected')) for r in ledger]).encode()).hexdigest()
    output_signature=sha256(json.dumps([(r.get('status'),(r.get('observed') or {}).get('frames'),(r.get('observed') or {}).get('game_mode')) for r in ledger]).encode()).hexdigest()
    outcome=dict(attempted=len(ledger),output_schedule_sha256=output_signature,model_stage_calls=report.get('model_stage_calls'),
                 reported_sample_rows=len(report['resource_samples']),failures=sum(r.get('status') not in {'delivered','interrupted'} for r in ledger),
                 cleanup=report['cleanup'],full_report_sha256=digest.hexdigest(),input_schedule_sha256=signature)
    del ledger
    await asyncio.sleep(0);gc.collect();point('report_held_after_gc',report)
    del report;await asyncio.sleep(0);gc.collect();point('report_released_after_gc')
    if traced:tracemalloc.stop()
    return dict(arm=arm,source_sha=SOURCE,attempt_limit=attempts,duration_limit=duration,**outcome,phases=phases,
                context_checkpoints=checkpoints,observer='same_weak_registry_in_plain_and_traced',
                attribution='unproven',rss_is_not_live_heap=True,production_modified=False)

def profile(output,attempts,timeout):
    if attempts not in (6,12,24) or type(timeout) is not int or not 10<=timeout<=120:raise Invalid('profile_bounds')
    # The caller must coordinate release first; never wait, steal, or replace lock.
    with heavy_lock() as lock_fd:
        output=Path(output);output.mkdir(exist_ok=False)
        with tempfile.TemporaryDirectory(prefix='v2-memory-frozen-') as folder:
            export=Path(folder)
            archive=subprocess.check_output(['git','archive',SOURCE,'backend','scripts','assets/v2-default'],timeout=10)
            import io
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:tar.extractall(export,filter='data')
            del archive
            results=[]
            for arm in ('plain','traced','traced_repeat','idle'):
                artifact=output.resolve()/(arm+'-full-soak.json')
                args=[sys.executable,'-I','-B',str(Path(__file__).resolve()),'_worker','--arm',arm,
                      '--attempts',str(attempts),'--artifact',str(artifact),'--execute-profile','--lock-fd',str(lock_fd)]
                try:
                    child=subprocess.run(args,cwd=export,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                         timeout=timeout,pass_fds=(lock_fd,),env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},check=True)
                    if len(child.stdout)>1024*1024:raise Invalid('worker_metadata_size')
                    result=json.loads(child.stdout)
                except Exception:
                    # Previous full reports remain; never retry another arm on a failed/unknown cleanup.
                    (output/'result.json').write_text(json.dumps(dict(status='worker_failed_stopped',completed=results,attribution='unknown')))
                    raise Invalid('worker_failed') from None
                results.append(result)
                (output/'result.json').write_text(json.dumps(dict(status='in_progress',completed=results,attribution='unknown'),indent=2))
                if not result['cleanup']['confirmed'] or result['cleanup']['pending_tasks'] or result['failures'] or (arm!='idle' and result['attempted']!=attempts):raise Invalid('workload_or_cleanup_failed')
            actual=results[:3]
            comparable=(len({r['input_schedule_sha256'] for r in actual})==1 and len({r['attempted'] for r in actual})==1 and
                        len({r['output_schedule_sha256'] for r in actual})==1 and len({json.dumps(r['model_stage_calls'],sort_keys=True) for r in actual})==1)
            report=dict(status='controls_collected_not_leak_verdict',source_sha=SOURCE,comparable=comparable,completed=results,
                        attribution='requires_review',idle_is_not_workload_control=True,cloud_calls=0,device_executed=False)
            (output/'result.json').write_text(json.dumps(report,indent=2)+'\n')
            return report

def cli(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    read=sub.add_parser('analyze');read.add_argument('--report',required=True);read.add_argument('--output',required=True)
    run=sub.add_parser('profile');run.add_argument('--execute-profile',action='store_true');run.add_argument('--attempts',type=int,default=12);run.add_argument('--timeout',type=int,default=30);run.add_argument('--output',required=True)
    child=sub.add_parser('_worker');child.add_argument('--arm',choices=('plain','traced','traced_repeat','idle'),required=True);child.add_argument('--attempts',type=int,choices=(6,12,24),required=True);child.add_argument('--artifact',required=True);child.add_argument('--execute-profile',action='store_true');child.add_argument('--lock-fd',type=int,default=-1)
    args=parser.parse_args(argv)
    try:
        if args.command=='analyze':
            result=analyze(args.report);Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
        elif args.command=='profile':
            if not args.execute_profile:raise Invalid('profile_disabled')
            result=profile(args.output,args.attempts,args.timeout)
        else:
            if not args.execute_profile or not sys.flags.isolated:raise Invalid('worker_requires_isolation')
            check_worker_lock(args.lock_fd)
            result=asyncio.run(worker(args.arm,args.attempts,args.artifact))
            print(json.dumps(result));return 0
        print(json.dumps(dict(memory_diagnostic='prepared' if args.command=='analyze' else 'controls_collected',profile_executed=args.command=='profile')));return 0
    except Exception:
        print('{"memory_diagnostic":"rejected_no_conclusion"}');return 2

if __name__=='__main__':raise SystemExit(cli())
