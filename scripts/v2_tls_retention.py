"""Frozen c486 TLS14 retention diagnostic PREPARATION, not a long-test verdict.

Default analyze is read-only. Actual children require explicit opt-in and the
original heavy.lock. No external provider/device or production configuration.
"""
import argparse
import asyncio
from collections import Counter
from contextlib import contextmanager
import gc
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import tarfile
import tempfile
import weakref

SOURCE='c4864f78868ab29f50713ca214f82554801c6248'
LOCK=Path('/var/lock/little-buddy/heavy.lock')
ARMS=('retain_plain','retain_traced','release_plain')
CATEGORIES=('diagnostic','tls_tool','sampling_tool','production','asyncio','ssl_python','other')
PHASES=('workload','connection_cleanup','post_connection_cleanup','global_cleanup','post_global_cleanup')
class Rejected(Exception):pass

def require(value):
    if not value:raise Rejected('incomplete_or_unconfirmed')
def integer(value):return type(value) is int and 0<=value<=10**12

def read_report(path):
    path=Path(path);require(path.is_file() and not path.is_symlink() and path.stat().st_size<=16*1024*1024)
    raw=path.read_bytes();report=json.loads(raw)
    require(type(report) is dict and report['layer']=='real_loopback_tls_tcp_relay_synthetic_asr_model_tts')
    require(report['cloud_enabled'] is False and report['device_executed'] is False)
    require(type(report['attempts']) is list and type(report['connection_ledger']) is list and len(report['attempts'])<=120)
    return raw,report

def analyze(path):
    raw,r=read_report(path);attempts=r['attempts'];ledger=r['connection_ledger']
    require(len(attempts)==len(ledger)==r['connections_attempted']==r['attempted'])
    require([row['index'] for row in attempts]==list(range(len(attempts)))==[row['index'] for row in ledger])
    require(all(integer(row['relay_network_errors']) for row in attempts+ledger))
    rss=r['resource_trends']['backend_rss_bytes'];require(integer(rss['first']) and integer(rss['last']))
    deltas=[dict(index=a['index'],attempt_snapshot=a['relay_network_errors'],final_ledger=b['relay_network_errors'],
                 delta=b['relay_network_errors']-a['relay_network_errors']) for a,b in zip(attempts,ledger)]
    return dict(format=1,source_sha=SOURCE,report_sha256=sha256(raw).hexdigest(),read_only=True,
        attempts=len(attempts),samples=len(r['resource_samples']),rss_delta_bytes=rss['last']-rss['first'],
        attempt_legacy_counter_total=sum(a['relay_network_errors'] for a in attempts),
        final_legacy_counter_total=sum(a['relay_network_errors'] for a in ledger),counter_deltas=deltas,
        counter_meaning='legacy_mixes_pipe_io_open_setup_and_reset_setup; snapshot_phases_differ',
        historical_syscall_cause='unproven',attribution='unknown',diagnostic_executed=False)

class ResetAccounting:
    """Mirror observations only: never repair/reset the producer's legacy count."""
    def __init__(self):self.reset_calls=Counter();self.reset_setup_errors=Counter();self.pipe_io_errors=Counter()
    def observe_reset(self,relay,phase,call):
        require(phase in PHASES);before=relay.network_errors;self.reset_calls[phase]+=1
        try:return call()
        finally:
            delta=relay.network_errors-before;require(integer(delta));self.reset_setup_errors[phase]+=delta
    def pipe_error(self,phase):require(phase in PHASES);self.pipe_io_errors[phase]+=1
    def metadata(self,legacy):
        classified=sum(self.reset_setup_errors.values())+sum(self.pipe_io_errors.values())
        return dict(legacy_total=legacy,reset_calls=dict(self.reset_calls),reset_setup_errors=dict(self.reset_setup_errors),
                    pipe_io_errors=dict(self.pipe_io_errors),unclassified_legacy=legacy-classified)

class WeakObjects:
    def __init__(self):self.refs={};self.unsupported=Counter()
    def watch(self,kind,obj):
        if obj is None:return
        refs=self.refs.setdefault(kind,{})
        if id(obj) in refs and refs[id(obj)]() is obj:return
        require(sum(map(len,self.refs.values()))<4096)
        try:refs[id(obj)]=weakref.ref(obj)
        except TypeError:self.unsupported[kind]+=1
    def metadata(self):return dict(live={k:sum(r() is not None for r in group.values()) for k,group in self.refs.items()},
                                   weak_slots=sum(map(len,self.refs.values())),unsupported_observations=dict(self.unsupported))

def census(owner,weak):
    tasks=owner.handles();writers=[]
    for peer in owner.peers:
        weak.watch('peer',peer);weak.watch('session',peer.session);weak.watch('websocket',peer.socket)
        transport=getattr(peer.socket,'transport',None);weak.watch('ssl_transport',transport)
        if transport is not None:weak.watch('ssl_object',transport.get_extra_info('ssl_object'))
    for relay in owner.relays:
        weak.watch('relay',relay)
        for pair in relay.links:
            for writer in pair:
                writers.append(writer);weak.watch('writer',writer);weak.watch('tcp_transport',writer.transport);weak.watch('reader_protocol',getattr(writer,'_protocol',None))
    for task in tasks:weak.watch('task',task)
    return dict(peer_slots=len(owner.peers),relay_slots=len(owner.relays),connection_row_slots=len(owner.connections),
                global_task_slots=len(owner.tasks),all_unique_task_handles=len(tasks),done_tasks=sum(t.done() for t in tasks),
                pending_tasks=sum(not t.done() for t in tasks),peer_history_task_slots=sum(len(p.retained) for p in owner.peers),
                relay_task_slots=sum(len(r.tasks) for r in owner.relays),writer_slots=len(writers),unique_writers=len({id(w) for w in writers}),
                **weak.metadata())

def confirm_closed_history(owner):
    """Reject unknown closure without dropping histories or changing product state."""
    require(owner.closed is True and owner.quarantined is False and owner.allowance.open is False and owner.ws is None)
    require(not owner.server.is_serving() and not owner.server.handler_tasks)
    for task in owner.handles():
        require(task.done())
        if not task.cancelled():require(task.exception() is None)
    for peer in owner.peers:
        require(peer.closed is True and peer.run_finished is True and peer.quarantined is False and peer.session.active is False and not peer.session.pending)
        require(not peer.generation_scopes)
        lost=getattr(peer.socket,'connection_lost_waiter',None)
        require(lost is not None and lost.done() and peer.socket.transport.is_closing())
        raw=peer.socket.transport.get_extra_info('socket');require(raw is None or raw.fileno()==-1)
    for row in owner.connections:
        require(row.get('cleanup_confirmed') is True and type(row.get('pending_after_cleanup')) is int and row['pending_after_cleanup']==0 and row.get('session_cleared') is True)
    for relay in owner.relays:
        require(not relay.open and not relay.server.is_serving())
        for pair in relay.links:
            for writer in pair:
                require(writer.is_closing() and writer.transport.is_closing())
                closed=getattr(getattr(writer,'_protocol',None),'_closed',None)
                require(closed is not None and closed.done()) # actual connection_lost notification, not just close requested
                raw=writer.get_extra_info('socket');require(raw is None or raw.fileno()==-1)

def release_closed_history(owner):
    """Post-run control ONLY, after full report preservation."""
    confirm_closed_history(owner)
    counts=dict(released_connection_rows=len(owner.connections),released_peer_slots=len(owner.peers),released_relay_slots=len(owner.relays))
    # These are test-tool histories, not production VoicePeer/Session fields.
    for relay in owner.relays:relay.links.clear();relay.tasks.clear()
    owner.peers.clear();owner.relays.clear();owner.connections.clear();owner.tasks.clear();owner.current=None
    return counts

def python_allocations(snapshot):
    result={k:0 for k in CATEGORIES}
    for item in snapshot.statistics('filename'):
        name=item.traceback[0].filename.replace('\\','/')
        group=('diagnostic' if name.endswith('/v2_tls_retention.py') else 'tls_tool' if name.endswith('/v2_tls_soak.py') else
               'sampling_tool' if name.endswith('/v2_soak.py') else 'production' if '/backend/v2/' in name else
               'asyncio' if '/asyncio/' in name else 'ssl_python' if name.endswith('/ssl.py') else 'other')
        result[group]+=item.size
    return result

def rss():
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith('VmRSS:'):return int(line.split()[1])*1024
    return None

@contextmanager
def heavy_lock(fd=None):
    import fcntl
    close=fd is None
    if close:
        info=LOCK.parent.lstat();require(stat.S_ISDIR(info.st_mode) and (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))==(0,0,0o755))
        fd=os.open(LOCK,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd);expected=LOCK.lstat()
        require(stat.S_ISREG(info.st_mode) and (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))==(0,0,0o644))
        require((info.st_dev,info.st_ino)==(expected.st_dev,expected.st_ino))
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise Rejected('lock_busy') from None
        yield fd
    finally:
        if close:os.close(fd)

async def worker(arm,nonce,artifact):
    # Imported only inside the opt-in, isolated child exported from SOURCE.
    sys.path.insert(0,str(Path.cwd()))
    from scripts import v2_tls_soak as net
    from unittest.mock import patch
    import tracemalloc
    weak=WeakObjects();boundaries=[];accounts={};relays={};state={'owner':None,'connections_seen':0}
    Transport,Relay=net.LoopbackTlsTransport,net.TcpRelay
    class ObservedRelay(Relay):
        def __init__(self,*a,**k):
            super().__init__(*a,**k);self.diag_phase='workload';self.account=ResetAccounting()
            accounts[id(self)]=self.account;relays[id(self)]=weakref.ref(self)
        def reset(self):return self.account.observe_reset(self,self.diag_phase,super().reset)
        async def pipe_bytes(self,*a,**k):
            try:return await super().pipe_bytes(*a,**k)
            except (OSError,ConnectionError):self.account.pipe_error(self.diag_phase);raise
        async def close(self,*a,**k):
            self.diag_phase='global_cleanup' if state['owner'].closed else 'connection_cleanup'
            try:return await super().close(*a,**k)
            finally:self.diag_phase='post_global_cleanup' if state['owner'].closed else 'post_connection_cleanup'
    class ObservedTransport(Transport):
        def __init__(self,*a,**k):super().__init__(*a,**k);state['owner']=self;weak.watch('owner',self)
        async def attempt(self,*a,**k):
            result=await super().attempt(*a,**k)
            state['connections_seen']+=1
            boundaries.append(dict(index=result['index'],phase='closed_before_attempt_task_return',
                                   lifetime_connections=state['connections_seen'],strong=census(self,weak)))
            return result
    traced=arm=='retain_traced';gc.collect()
    if traced:tracemalloc.start(8)
    points=[]
    def point(label):
        owner=state['owner']
        row=dict(phase=label,rss_bytes=rss(),strong=None if owner is None else census(owner,weak),weak=weak.metadata(),
                 python_current=None,python_peak=None,tracer_metadata=None,python_allocation_groups=None)
        if traced:
            row['python_current'],row['python_peak']=tracemalloc.get_traced_memory();row['tracer_metadata']=tracemalloc.get_tracemalloc_memory()
            snap=tracemalloc.take_snapshot();row['python_allocation_groups']=python_allocations(snap);del snap
        points.append(row)
    point('baseline_after_import_gc')
    with patch.multiple(net,LoopbackTlsTransport=ObservedTransport,TcpRelay=ObservedRelay):
        report=await net.run_tls_soak(net.Limits(duration=12,interval=.05,sample_interval=.05,attempt_timeout=2,max_attempts=14),seed=17)
    point('report_held_owner_held')
    with open(artifact,'x') as out:json.dump(report,out,sort_keys=True)
    full_hash=sha256(Path(artifact).read_bytes()).hexdigest()
    # Snapshot accounting before any controlled dropping of diagnostic histories.
    counters=[dict(index=i,**accounts[id(relay)].metadata(relay.network_errors)) for i,relay in enumerate(state['owner'].relays)]
    await asyncio.sleep(0);gc.collect();point('report_saved_loop_gc_owner_held')
    require(report['cleanup']['confirmed'] is True and report['cleanup']['pending_tasks']==0 and report['cleanup']['errors']==0 and report['cleanup']['isolated'] is False)
    require(report['attempted']==report['connections_attempted']==report['peers_constructed']==14 and report['failures']==0)
    require(report['resource_collection_valid'] is True and type(report['collection_errors']) is int and report['collection_errors']==0)
    require(report['observations']>=len(report['resource_samples'])>0)
    confirm_closed_history(state['owner'])
    control=None
    if arm=='release_plain':control=release_closed_history(state['owner'])
    point('confirmed_history_control' if control else 'history_retained_control')
    outcome=dict(attempted=report['attempted'],full_report_sha256=full_hash,full_report_bytes=Path(artifact).stat().st_size,
                 observations=report['observations'],retained_samples=len(report['resource_samples']),
                 model_stage_calls=report['model_stage_calls'],allowance=report['allowance'],cleanup=report['cleanup'])
    del report;await asyncio.sleep(0);gc.collect();point('report_released_owner_held')
    confirm_closed_history(state['owner'])
    state['owner']=None;await asyncio.sleep(0);gc.collect();point('observer_owner_released_loop_gc')
    if traced:tracemalloc.stop()
    return dict(format=1,source_sha=SOURCE,arm=arm,nonce=nonce,**outcome,points=points,connection_boundaries=boundaries,
                lifetime_connections=state['connections_seen'],release_control=control,relay_accounting=counters,
                tracer_frames=8 if traced else 0,attribution='unknown',native_tls_allocations_measured=False)

FAULTS=('normal_close','asr_rst','plan_rst','partial_rst','pause_resume','half_open','playback_stop')
POINTS=('baseline_after_import_gc','report_held_owner_held','report_saved_loop_gc_owner_held',
        'history_retained_control','report_released_owner_held','observer_owner_released_loop_gc')
WEAK_KINDS={'owner','peer','session','websocket','relay','writer','tcp_transport','task','ssl_transport','ssl_object','reader_protocol'}
STRONG_KEYS={'peer_slots','relay_slots','connection_row_slots','global_task_slots','all_unique_task_handles','done_tasks','pending_tasks',
             'peer_history_task_slots','relay_task_slots','writer_slots','unique_writers'}

def counts(value,allowed):return type(value) is dict and value.keys()<=allowed and all(integer(v) for v in value.values())

def weak_metadata(value):
    require(type(value) is dict and value.keys()=={'live','weak_slots','unsupported_observations'})
    require(counts(value['live'],WEAK_KINDS) and counts(value['unsupported_observations'],WEAK_KINDS) and integer(value['weak_slots']) and value['weak_slots']<=4096)

def strong_metadata(value):
    require(type(value) is dict and value.keys()==STRONG_KEYS|{'live','weak_slots','unsupported_observations'})
    require(all(integer(value[k]) for k in STRONG_KEYS))
    weak_metadata({k:value[k] for k in ('live','weak_slots','unsupported_observations')})
    require(value['done_tasks']+value['pending_tasks']==value['all_unique_task_handles'])

def validate_child(result,arm,nonce,artifact):
    require(type(result) is dict and result.keys()=={'format','source_sha','arm','nonce','attempted','full_report_sha256','retained_samples',
        'full_report_bytes','observations','model_stage_calls','allowance','cleanup','points','connection_boundaries','lifetime_connections','release_control',
        'relay_accounting','tracer_frames','attribution','native_tls_allocations_measured'})
    require(type(result['format']) is int and result['format']==1 and result['source_sha']==SOURCE and result['arm']==arm and result['nonce']==nonce)
    for key in ('attempted','lifetime_connections'):require(type(result[key]) is int and result[key]==14)
    require(result['attribution']=='unknown' and result['native_tls_allocations_measured'] is False)
    require(type(result['tracer_frames']) is int and result['tracer_frames']==(8 if arm=='retain_traced' else 0))
    require(integer(result['retained_samples']) and 0<result['retained_samples']<=4096)
    require(counts(result['model_stage_calls'],{'endpoint','plan','facts','safe','compact'}))
    require(type(result['points']) is list and len(result['points'])==6)
    labels=list(POINTS)
    if arm=='release_plain':labels[3]='confirmed_history_control'
    for label,point in zip(labels,result['points']):
        require(type(point) is dict and point.keys()=={'phase','rss_bytes','strong','weak','python_current','python_peak','tracer_metadata','python_allocation_groups'})
        require(point['phase']==label and integer(point['rss_bytes']))
        weak_metadata(point['weak'])
        if label in (labels[0],labels[-1]):require(point['strong'] is None)
        else:strong_metadata(point['strong'])
        if arm=='retain_traced':
            require(all(integer(point[k]) for k in ('python_current','python_peak','tracer_metadata')))
            require(point['python_peak']>=point['python_current'] and counts(point['python_allocation_groups'],set(CATEGORIES)) and point['python_allocation_groups'].keys()==set(CATEGORIES))
        else:require(all(point[k] is None for k in ('python_current','python_peak','tracer_metadata','python_allocation_groups')))
    if arm=='release_plain':require(result['release_control']==dict(released_connection_rows=14,released_peer_slots=14,released_relay_slots=14))
    else:require(result['release_control'] is None)
    for index in (1,2):
        require(all(result['points'][index]['strong'][k]==14 for k in ('peer_slots','relay_slots','connection_row_slots')))
    for index in (3,4):
        require(all(result['points'][index]['strong'][k]==(0 if arm=='release_plain' else 14) for k in ('peer_slots','relay_slots','connection_row_slots')))
    require(type(result['connection_boundaries']) is list and len(result['connection_boundaries'])==14)
    for index,row in enumerate(result['connection_boundaries']):
        require(type(row) is dict and row.keys()=={'index','phase','lifetime_connections','strong'} and type(row['index']) is int and row['index']==index)
        require(row['phase']=='closed_before_attempt_task_return' and type(row['lifetime_connections']) is int and row['lifetime_connections']==index+1)
        strong_metadata(row['strong'])
    raw,r=read_report(artifact);require(sha256(raw).hexdigest()==result['full_report_sha256'])
    require(type(result['full_report_bytes']) is int and result['full_report_bytes']==len(raw))
    require(type(result['observations']) is int and result['observations']==r['observations'])
    require(all(type(r[k]) is int and r[k]==14 for k in ('attempted','connections_attempted','peers_constructed')))
    require(len(r['attempts'])==len(r['connection_ledger'])==14)
    cleanup=r['cleanup'];require(type(cleanup) is dict and cleanup.keys()=={'confirmed','pending_tasks','errors','isolated'})
    require(cleanup['confirmed'] is True and cleanup['isolated'] is False and all(type(cleanup[k]) is int and cleanup[k]==0 for k in ('pending_tasks','errors')))
    require(cleanup==result['cleanup'] and r['resource_collection_valid'] is True and type(r['collection_errors']) is int and r['collection_errors']==0)
    require(type(r['resource_samples']) is list and type(r['observations']) is int and r['observations']>=len(r['resource_samples'])==result['retained_samples']>0)
    require(all(type(row) is dict and integer(row.get('backend_rss_bytes')) for row in r['resource_samples']))
    for index,row in enumerate(r['attempts']):
        fault=FAULTS[index//2] if index%2==0 else 'normal_close'
        status='interrupted' if fault=='playback_stop' else 'fault_injected' if fault in {'asr_rst','plan_rst','partial_rst','half_open'} else 'delivered'
        require(type(row['index']) is int and row['index']==index and row['fault']==fault and row['status']==status)
        require(row['cleanup_confirmed'] is True and row['session_cleared'] is True and type(row['pending_after_cleanup']) is int and row['pending_after_cleanup']==0 and row['new_session'] is True)
    allowance=result['allowance']
    require(type(allowance) is dict and allowance.keys()=={'model_calls','tts_calls','tts_unicode_characters','reserved_units','account_quota_known','bill_cny'})
    require(all(integer(allowance[k]) for k in ('model_calls','tts_calls','tts_unicode_characters','reserved_units')))
    require(allowance['account_quota_known'] is False and allowance['bill_cny'] is None)
    require(r['model_stage_calls']==result['model_stage_calls'] and r['allowance']==allowance and type(r['failures']) is int and r['failures']==0)
    require(type(result['relay_accounting']) is list and len(result['relay_accounting'])==14)
    for index,row in enumerate(result['relay_accounting']):
        require(type(row) is dict and row.keys()=={'index','legacy_total','reset_calls','reset_setup_errors','pipe_io_errors','unclassified_legacy'})
        require(type(row['index']) is int and row['index']==index)
        require(all(integer(row[k]) for k in ('legacy_total','unclassified_legacy')))
        require(all(counts(row[k],set(PHASES)) for k in ('reset_calls','reset_setup_errors','pipe_io_errors')))
        require(row['legacy_total']==sum(row['reset_setup_errors'].values())+sum(row['pipe_io_errors'].values())+row['unclassified_legacy'])
        require(row['legacy_total']==r['connection_ledger'][index]['relay_network_errors'])


def run(output,arm='retain_plain'):
    require(arm in ARMS)
    with heavy_lock() as fd:
        output=Path(output);output.mkdir(exist_ok=False);results=[]
        try:
            with tempfile.TemporaryDirectory(prefix='tls14-frozen-') as folder:
                export=Path(folder)
                archive=subprocess.check_output(['git','archive',SOURCE,'backend','scripts','assets/v2-default'],timeout=10)
                with tarfile.open(fileobj=io.BytesIO(archive)) as tar:tar.extractall(export,filter='data')
                del archive
                for arm in (arm,):
                    nonce=secrets.token_hex(16);artifact=output.resolve()/(arm+'-full-report.json')
                    args=[sys.executable,'-I','-B',str(Path(__file__).resolve()),'_child','--enable','--lock-fd',str(fd),'--arm',arm,'--nonce',nonce,'--artifact',str(artifact)]
                    child=subprocess.run(args,cwd=export,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                         timeout=45,check=True,pass_fds=(fd,),env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
                    require(len(child.stdout)<=1024*1024);result=json.loads(child.stdout)
                    validate_child(result,arm,nonce,artifact);results.append(result)
                    (output/(arm+'-diagnostic.json')).write_text(json.dumps(result,indent=2)+'\n')
                summary=dict(status='controls_collected_not_attribution',source_sha=SOURCE,completed=results,attribution='unknown')
                (output/'result.json').write_text(json.dumps(summary,indent=2)+'\n');return summary
        except Exception:
            (output/'result.json').write_text(json.dumps(dict(status='failed_or_unknown_stopped',completed=results,attribution='unknown'))+'\n')
            raise Rejected('diagnostic_stopped') from None

def cli(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('analyze');a.add_argument('--report',required=True);a.add_argument('--output',required=True)
    r=sub.add_parser('short14');r.add_argument('--enable',action='store_true');r.add_argument('--output',required=True);r.add_argument('--arm',choices=ARMS,default='retain_plain')
    c=sub.add_parser('_child');c.add_argument('--enable',action='store_true');c.add_argument('--lock-fd',type=int,default=-1);c.add_argument('--arm',choices=ARMS,required=True);c.add_argument('--nonce',required=True);c.add_argument('--artifact',required=True)
    args=p.parse_args(argv)
    try:
        if args.command=='analyze':Path(args.output).write_text(json.dumps(analyze(args.report),indent=2)+'\n')
        elif args.command=='short14':
            require(args.enable);run(args.output,args.arm)
        else:
            require(args.enable and sys.flags.isolated and args.lock_fd>=0 and len(args.nonce)==32 and all(x in '0123456789abcdef' for x in args.nonce))
            with heavy_lock(args.lock_fd):print(json.dumps(asyncio.run(worker(args.arm,args.nonce,args.artifact))))
        return 0
    except Exception:print('{"tls_retention":"rejected_no_attribution"}');return 2
if __name__=='__main__':raise SystemExit(cli())
