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
import math
import secrets
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

async def worker(arm,attempts,artifact,worker_id):
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
        report=dict(attempts=[],resource_samples=[],sampling=dict(observations=0,evicted=0),cleanup=dict(confirmed=True,pending_tasks=0,provider_reusable=None))
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
    structure=dict(attempt_rows=len(ledger),retained_sample_rows=len(report['resource_samples']),
                   sample_observations=report['sampling']['observations'],sample_evicted=report['sampling']['evicted'],
                   top_level_fields=len(report),file_bytes=Path(artifact).stat().st_size)
    outcome=dict(report_structure=structure,attempted=len(ledger),output_schedule_sha256=output_signature,model_stage_calls=report.get('model_stage_calls'),
                 reported_sample_rows=len(report['resource_samples']),failures=sum(r.get('status') not in {'delivered','interrupted'} for r in ledger),
                 cleanup=report['cleanup'],full_report_sha256=digest.hexdigest(),input_schedule_sha256=signature)
    del ledger
    await asyncio.sleep(0);gc.collect();point('report_held_after_gc',report)
    del report;await asyncio.sleep(0);gc.collect();point('report_released_after_gc')
    if traced:tracemalloc.stop()
    return dict(format=2,worker_id=worker_id,arm=arm,source_sha=SOURCE,attempt_limit=attempts,duration_limit=duration,**outcome,phases=phases,
                context_checkpoints=checkpoints,measurement_overhead=dict(phase_rows=len(phases),context_checkpoint_rows=len(checkpoints),
                    weak_registry_observations=registry.observations,weak_slots=sum(map(len,registry.refs.values())),tracer_frames=8 if traced else 0),observer='same_weak_registry_in_plain_and_traced',
                attribution='unproven',rss_is_not_live_heap=True,production_modified=False)

PHASES=('baseline_after_import_gc','returned_report_held','report_held_after_gc','report_released_after_gc')
KINDS=frozenset(('task','operation','ownership','transport','peer','session','collector'))
COUNTERS=frozenset(('owner_task_handles','owner_done_task_handles','owner_pending',*(
    'session_'+name+'_size' for name in ('public','private','recent','facts','source_archive','pending','game','secrets'))))
FAILURE_CODES=frozenset(('worker_identity_invalid','worker_metadata_invalid','worker_artifact_invalid','worker_failed','comparison_failed'))

def integer(value,maximum=10**12):return type(value) is int and 0<=value<=maximum

def digest(value):return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)

def ensure(condition):
    if not condition:raise Invalid('worker_metadata_invalid')

def counters(value,keys):
    return type(value) is dict and value.keys()<=keys and all(integer(v) for v in value.values())

def schedule_hashes(report):
    ledger=report['attempts']
    inputs=sha256(json.dumps([(r.get('index'),r.get('scenario'),r.get('injected')) for r in ledger]).encode()).hexdigest()
    outputs=sha256(json.dumps([(r.get('status'),(r.get('observed') or {}).get('frames'),(r.get('observed') or {}).get('game_mode')) for r in ledger]).encode()).hexdigest()
    return inputs,outputs

def validate_worker(result,arm,attempts,worker_id,artifact):
    """Only a fully bound, typed result may enter completed. No success defaults."""
    if (type(result) is not dict or result.get('format')!=2 or type(result.get('format')) is not int or
        result.get('worker_id')!=worker_id or result.get('arm')!=arm or result.get('source_sha')!=SOURCE or
        type(result.get('attempt_limit')) is not int or result['attempt_limit']!=attempts):raise Invalid('worker_identity_invalid')
    keys={'format','worker_id','arm','source_sha','attempt_limit','duration_limit','attempted','failures','cleanup',
          'full_report_sha256','input_schedule_sha256','output_schedule_sha256','model_stage_calls',
          'reported_sample_rows','report_structure','phases','context_checkpoints','measurement_overhead',
          'observer','attribution','rss_is_not_live_heap','production_modified'}
    try:
        ensure(result.keys()==keys)
        ensure(type(result['duration_limit']) in (int,float) and math.isfinite(result['duration_limit']) and result['duration_limit']==max(3.,attempts*.3))
        ensure(integer(result['attempted'],attempts) and integer(result['failures'],result['attempted']))
        cleanup=result['cleanup']
        ensure(type(cleanup) is dict and cleanup.keys()=={'confirmed','pending_tasks','provider_reusable'})
        ensure(type(cleanup['confirmed']) is bool and integer(cleanup['pending_tasks']))
        ensure(type(cleanup['provider_reusable']) is bool if arm!='idle' else cleanup['provider_reusable'] is None)
        ensure(all(digest(result[k]) for k in ('full_report_sha256','input_schedule_sha256','output_schedule_sha256')))
        calls=result['model_stage_calls']
        ensure(calls is None if arm=='idle' else counters(calls,{'plan','facts','safe','compact'}))
        structure=result['report_structure']
        ensure(type(structure) is dict and structure.keys()=={'attempt_rows','retained_sample_rows','sample_observations','sample_evicted','top_level_fields','file_bytes'})
        ensure(all(integer(v) for v in structure.values()))
        ensure(integer(result['reported_sample_rows'],4096) and structure['retained_sample_rows']==result['reported_sample_rows'])
        ensure(structure['attempt_rows']==result['attempted'] and structure['sample_observations']-structure['retained_sample_rows']==structure['sample_evicted'])
        ensure(structure['file_bytes']<=16*1024*1024)
        overhead=result['measurement_overhead']
        ensure(type(overhead) is dict and overhead.keys()=={'phase_rows','context_checkpoint_rows','weak_registry_observations','weak_slots','tracer_frames'})
        ensure(all(integer(v) for v in overhead.values()) and overhead['weak_slots']<=min(8192,overhead['weak_registry_observations']))
        ensure(overhead['tracer_frames']==(0 if arm=='plain' else 8))
        ensure(result['observer']=='same_weak_registry_in_plain_and_traced' and result['attribution']=='unproven')
        ensure(result['rss_is_not_live_heap'] is True and result['production_modified'] is False)
        phases=result['phases']
        ensure(type(phases) is list and len(phases)==overhead['phase_rows']==4)
        for expected,row in zip(PHASES,phases):
            ensure(type(row) is dict and row.keys()=={'phase','rss_bytes','live','counts','trace_current','trace_peak','trace_metadata_bytes','allocation_groups','report_reachable_bytes'})
            ensure(row['phase']==expected and (row['rss_bytes'] is None or integer(row['rss_bytes'])))
            ensure(row['report_reachable_bytes'] is None if expected in (PHASES[0],PHASES[3]) else integer(row['report_reachable_bytes']))
            ensure(counters(row['counts'],COUNTERS) and type(row['live']) is dict and row['live'].keys()<=KINDS)
            for value in row['live'].values():
                ensure(type(value) is dict and value.keys()=={'observed','retained_weak_slots','live'} and all(integer(v) for v in value.values()))
                ensure(value['live']<=value['retained_weak_slots']<=value['observed'])
            if arm=='plain':ensure(all(row[k] is None for k in ('trace_current','trace_peak','trace_metadata_bytes','allocation_groups')))
            else:
                ensure(all(integer(row[k]) for k in ('trace_current','trace_peak','trace_metadata_bytes')) and row['trace_peak']>=row['trace_current'])
                groups=row['allocation_groups'];ensure(type(groups) is dict and groups.keys()==set(GROUPS))
                for group in groups.values():ensure(type(group) is dict and group.keys()=={'bytes','blocks'} and all(integer(v) for v in group.values()))
        checkpoints=result['context_checkpoints']
        ensure(type(checkpoints) is list and len(checkpoints)==overhead['context_checkpoint_rows'])
        ensure(len(checkpoints)==(0 if arm=='idle' else result['attempted']))
        for index,row in enumerate(checkpoints):
            ensure(counters(row,COUNTERS|{'index','sample_rows','observations'}) and {'index','sample_rows','observations'}<=row.keys() and row['index']==index)
    except (AssertionError,KeyError,TypeError,ValueError):raise Invalid('worker_metadata_invalid') from None
    try:
        info=artifact.lstat()
        ensure(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size==structure['file_bytes']<=16*1024*1024)
        raw=artifact.read_bytes();ensure(sha256(raw).hexdigest()==result['full_report_sha256'])
        full=json.loads(raw);ensure(type(full) is dict and len(full)==structure['top_level_fields'])
        ensure(type(full['attempts']) is list and len(full['attempts'])==result['attempted'])
        ensure(type(full['resource_samples']) is list and len(full['resource_samples'])==result['reported_sample_rows'])
        ensure(full['sampling']['observations']==structure['sample_observations'] and full['sampling']['evicted']==structure['sample_evicted'])
        ensure(full['cleanup']==cleanup and full.get('model_stage_calls')==calls)
        ensure(schedule_hashes(full)==(result['input_schedule_sha256'],result['output_schedule_sha256']))
        ensure(sum(row.get('status') not in {'delivered','interrupted'} for row in full['attempts'])==result['failures'])
        if arm!='idle':ensure(full['cloud_enabled'] is False and full['device_executed'] is False)
    except Exception:raise Invalid('worker_artifact_invalid') from None


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
                artifact=output.resolve()/(arm+'-full-soak.json');worker_id=secrets.token_hex(16)
                args=[sys.executable,'-I','-B',str(Path(__file__).resolve()),'_worker','--arm',arm,
                      '--attempts',str(attempts),'--artifact',str(artifact),'--execute-profile','--lock-fd',str(lock_fd),'--worker-id',worker_id]
                try:
                    child=subprocess.run(args,cwd=export,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                         timeout=timeout,pass_fds=(lock_fd,),env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},check=True)
                    if len(child.stdout)>1024*1024:raise Invalid('worker_metadata_invalid')
                    result=json.loads(child.stdout)
                    validate_worker(result,arm,attempts,worker_id,artifact)
                    results.append(result)
                    if not result['cleanup']['confirmed'] or result['cleanup']['pending_tasks'] or result['failures'] or (arm!='idle' and result['attempted']!=attempts):
                        (output/'result.json').write_text(json.dumps(dict(status='workload_or_cleanup_failed_stopped',completed=results,attribution='unknown')))
                        raise Invalid('workload_or_cleanup_failed')
                    (output/'result.json').write_text(json.dumps(dict(status='in_progress',completed=results,attribution='unknown'),indent=2))
                except Exception as error:
                    code=str(error) if isinstance(error,Invalid) and str(error) in FAILURE_CODES|{'workload_or_cleanup_failed'} else 'worker_failed'
                    status='workload_or_cleanup_failed_stopped' if code=='workload_or_cleanup_failed' else 'worker_failed_stopped'
                    (output/'result.json').write_text(json.dumps(dict(status=status,failed_arm=arm,failure=code,completed=results,
                        artifact_preserved=artifact.exists(),attribution='unknown')))
                    raise Invalid(code) from None
            actual=results[:3]
            try:
                workload_schedule_comparable=(len({r['input_schedule_sha256'] for r in actual})==1 and len({r['attempted'] for r in actual})==1 and
                            len({r['output_schedule_sha256'] for r in actual})==1 and len({json.dumps(r['model_stage_calls'],sort_keys=True) for r in actual})==1)
                comparable=(len({r['reported_sample_rows'] for r in actual})==1 and
                            len({json.dumps(r.get('report_structure'),sort_keys=True) for r in actual})==1 and
                            len({json.dumps(r.get('measurement_overhead'),sort_keys=True) for r in actual})==1 and
                            len({json.dumps([p.get('report_reachable_bytes') for p in r.get('phases',[])]) for r in actual})==1 and
                            len({r['input_schedule_sha256'] for r in actual})==1 and len({r['attempted'] for r in actual})==1 and
                            len({r['output_schedule_sha256'] for r in actual})==1 and len({json.dumps(r['model_stage_calls'],sort_keys=True) for r in actual})==1)
                memory_controls=dict(comparable=comparable,criterion='same_observed_report_structure_and_measurement_work_not_production_identity',
                    retained_sample_rows_equal=len({r['reported_sample_rows'] for r in actual})==1,
                    measurement_conditions_equal=len({json.dumps(r['measurement_overhead'],sort_keys=True) for r in actual})==1,
                    arms=[dict(arm=r['arm'],report_structure=r['report_structure'],measurement_overhead=r['measurement_overhead'],
                        held_report_reachable_bytes=[p['report_reachable_bytes'] for p in r['phases']],
                        tracer_metadata_bytes=[p['trace_metadata_bytes'] for p in r['phases']]) for r in actual])
                report=dict(status='controls_collected_not_leak_verdict',source_sha=SOURCE,comparable=comparable,
                            comparable_scope='memory_controls_conservative_not_workload_only',workload_schedule_comparable=workload_schedule_comparable,
                            memory_controls=memory_controls,completed=results,attribution='requires_review',idle_is_not_workload_control=True,
                            cloud_calls=0,device_executed=False)
            except Exception:
                (output/'result.json').write_text(json.dumps(dict(status='comparison_failed_stopped',completed=results,attribution='unknown')))
                raise Invalid('comparison_failed') from None
            (output/'result.json').write_text(json.dumps(report,indent=2)+'\n')
            return report

def cli(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    read=sub.add_parser('analyze');read.add_argument('--report',required=True);read.add_argument('--output',required=True)
    run=sub.add_parser('profile');run.add_argument('--execute-profile',action='store_true');run.add_argument('--attempts',type=int,default=12);run.add_argument('--timeout',type=int,default=30);run.add_argument('--output',required=True)
    child=sub.add_parser('_worker');child.add_argument('--arm',choices=('plain','traced','traced_repeat','idle'),required=True);child.add_argument('--attempts',type=int,choices=(6,12,24),required=True);child.add_argument('--artifact',required=True);child.add_argument('--execute-profile',action='store_true');child.add_argument('--lock-fd',type=int,default=-1);child.add_argument('--worker-id',default='')
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
            if len(args.worker_id)!=32 or any(c not in '0123456789abcdef' for c in args.worker_id):raise Invalid('worker_identity_invalid')
            result=asyncio.run(worker(args.arm,args.attempts,args.artifact,args.worker_id))
            print(json.dumps(result));return 0
        print(json.dumps(dict(memory_diagnostic='prepared' if args.command=='analyze' else 'controls_collected',profile_executed=args.command=='profile')));return 0
    except Exception:
        print('{"memory_diagnostic":"rejected_no_conclusion"}');return 2

if __name__=='__main__':raise SystemExit(cli())
