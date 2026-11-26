"""Only toy graphs, fake counters, archive/process/lock; no real TLS or trace."""
from contextlib import contextmanager,redirect_stdout
from hashlib import sha256
import gc
import io
import json
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from scripts import v2_tls_retention as m

class Done:
    def __init__(self,done=True,error=None):self.ready=done;self.error=error
    def done(self):return self.ready
    def cancelled(self):return False
    def exception(self):return self.error
class Server:
    def __init__(self):self.serving=False;self.handler_tasks=set()
    def is_serving(self):return self.serving
class Transport:
    def __init__(self):self.closing=True
    def is_closing(self):return self.closing
    def get_extra_info(self,key):return None
class Writer:
    def __init__(self):self.transport=Transport();self._protocol=NS(_closed=Done());self.fd=-1
    def is_closing(self):return self.transport.closing
    def get_extra_info(self,key):return NS(fileno=lambda:self.fd)
class Peer:
    def __init__(self):
        self.closed=True;self.run_finished=True;self.quarantined=False;self.session=Session()
        self.generation_scopes={};self.retained={Done()};self.socket=NS(transport=Transport(),connection_lost_waiter=Done())
class Session:
    def __init__(self):self.active=False;self.pending=[]
class Owner:
    def __init__(self):
        self.closed=True;self.quarantined=False;self.allowance=NS(open=False);self.ws=None;self.server=Server()
        self.peers=[Peer()];self.relays=[NS(open=False,server=Server(),links=[(Writer(),Writer())],tasks={Done()})]
        self.connections=[dict(peer=self.peers[0],relay=self.relays[0],cleanup_confirmed=True,pending_after_cleanup=0,session_cleared=True)]
        self.tasks={Done()};self.current=self.connections[0]
    def handles(self):return self.tasks|set().union(*(r.tasks for r in self.relays))|set().union(*(p.retained for p in self.peers))

def semantic_fixture(args):
    """Synthetic wire facts modelled on c486's saved rows, not real execution."""
    def value(key):return args[args.index(key)+1]
    arm=value('--arm');nonce=value('--nonce');artifact=Path(value('--artifact'))
    rows=[];samples=[]
    for i in range(14):
        fault=m.FAULTS[i//2] if i%2==0 else 'normal_close'
        status='interrupted' if fault=='playback_stop' else 'fault_injected' if fault in {'asr_rst','plan_rst','partial_rst','half_open'} else 'delivered'
        delivered=status=='delivered';silent=fault in {'asr_rst','plan_rst'};frames=0 if silent else 4 if delivered else 1
        start=round(i*.1,3);end=round(start+.08,3)
        rows.append(dict(index=i,fault=fault,status=status,frames=frames,acks=frames if delivered else 0 if silent else 1,
            cleanup_confirmed=True,pending_after_cleanup=0,failure=None,session_cleared=True,old_heard_count=0,new_session=True,
            old_ack_checked=True if frames and i>0 else None,control=None,heard_before_close=1 if delivered else 0,
            pending_before_close=2 if fault=='half_open' else 1 if fault=='partial_rst' else 0,
            game_mode='chat' if delivered else None,started_seconds=start,completed_seconds=end,
            rst_applied=True if status=='fault_injected' else None,relay_network_errors=1,
            pause_observed=True if fault in {'pause_resume','half_open'} else None,close_handshake_confirmed=delivered or fault=='playback_stop',
            first_transport_ms=None if silent else 1.,relay_bytes=dict(up=100,down=200),relay_buffer_observed_max=100,
            injected_half_open_seconds=.05 if fault=='half_open' else None,injected_pause_seconds=.05 if fault=='pause_resume' else None))
        phases=['attempt_started','initial']+([] if fault=='asr_rst' else ['operation_started'])+['before_network_fault','after_network_fault','before_transport_cleanup','after_transport_cleanup','attempt_finished']
        for j,label in enumerate(phases):
            sample=dict({k:0 for k in m.METRICS},elapsed=end if label=='attempt_finished' else round(start+j*.01,3),phase=label,device_rss_bytes=None)
            sample.update(backend_rss_bytes=100+i,backend_fds=7,backend_threads=1,asyncio_tasks=1,transport_tasks_pending=1)
            if label in {'initial','operation_started','before_network_fault','after_network_fault','before_transport_cleanup'}:sample['active_sessions']=1
            if label in {'operation_started','before_network_fault','after_network_fault','before_transport_cleanup'}:
                if fault=='asr_rst':sample.update(asr_active=1,recognition_operations=1,capture_bytes=640)
                else:sample['active_operations']=1
            samples.append(sample)
    final=dict({k:0 for k in m.METRICS},elapsed=1.5,phase='final',device_rss_bytes=None)
    final.update(backend_rss_bytes=114,backend_fds=7,backend_threads=1,asyncio_tasks=1);samples.append(final)
    trends={k:dict(first=samples[0][k],last=samples[-1][k],maximum=max(row[k] for row in samples),maximum_kind='observed_sample_maximum') for k in m.METRICS}
    cleanup=dict(confirmed=True,pending_tasks=0,errors=0,isolated=False);calls=dict(endpoint=13,plan=13,facts=13,safe=12)
    allowance=dict(model_calls=51,tts_calls=12,tts_unicode_characters=84,reserved_units=63,account_quota_known=False,bill_cny=None)
    full=dict(layer='real_loopback_tls_tcp_relay_synthetic_asr_model_tts',cloud_enabled=False,device_executed=False,
        attempted=14,connections_attempted=14,peers_constructed=14,attempts=rows,connection_ledger=[dict(row) for row in rows],
        cleanup=cleanup,resource_collection_valid=True,collection_errors=0,observations=len(samples),resource_samples=samples,resource_trends=trends,
        elapsed_seconds=1.5,requested_seconds=12,seed=17,stop_reason='attempt_cap',model_stage_calls=calls,allowance=allowance,failures=0)
    raw=json.dumps(full).encode();artifact.write_bytes(raw)
    weak=dict(live={},weak_slots=0,unsupported_observations={})
    def strong(n):return dict({k:0 for k in m.STRONG_KEYS},peer_slots=n,relay_slots=n,connection_row_slots=n,**weak)
    points=[]
    for index,label in enumerate(m.POINTS):
        if index==3 and arm=='release_plain':label='confirmed_history_control'
        traced=arm=='retain_traced'
        points.append(dict(phase=label,rss_bytes=100,strong=None if index in (0,5) else strong(0 if index>=3 and arm=='release_plain' else 14),weak=weak,
            python_current=10 if traced else None,python_peak=20 if traced else None,tracer_metadata=2 if traced else None,
            python_allocation_groups={k:0 for k in m.CATEGORIES} if traced else None))
    result=dict(format=1,source_sha=m.SOURCE,arm=arm,nonce=nonce,attempted=14,full_report_sha256=sha256(raw).hexdigest(),full_report_bytes=len(raw),observations=len(samples),retained_samples=len(samples),
        model_stage_calls=calls,allowance=allowance,cleanup=cleanup,points=points,
        connection_boundaries=[dict(index=i,phase='closed_before_attempt_task_return',lifetime_connections=i+1,strong=strong(i+1)) for i in range(14)],
        lifetime_connections=14,release_control=dict(released_connection_rows=14,released_peer_slots=14,released_relay_slots=14) if arm=='release_plain' else None,
        relay_accounting=[dict(index=i,legacy_total=1,reset_calls={'global_cleanup':1},reset_setup_errors={'global_cleanup':1},pipe_io_errors={},unclassified_legacy=0) for i in range(14)],
        tracer_frames=8 if arm=='retain_traced' else 0,attribution='unknown',native_tls_allocations_measured=False)
    return NS(stdout=json.dumps(result).encode(),stderr=b'',returncode=0)

class Preparation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def test_closed_history_release_preserves_saved_denominator_and_weakrefs_are_not_owners(self):
        owner=Owner();weak=m.WeakObjects();m.census(owner,weak)
        saved=json.dumps(dict(attempted=14,connection_ledger=[dict(index=i) for i in range(14)]))
        before=json.loads(saved);result=m.release_closed_history(owner);gc.collect()
        self.assertEqual(result['released_connection_rows'],1)
        self.assertEqual(owner.connections,[]);self.assertEqual(owner.tasks,set());self.assertIsNone(owner.current)
        self.assertEqual(weak.metadata()['live']['peer'],0);self.assertEqual(weak.metadata()['live']['writer'],0)
        self.assertEqual(json.loads(saved),before);self.assertEqual(before['attempted'],14)
    def test_any_unconfirmed_resource_rejects_atomically_and_keeps_histories(self):
        changes=[lambda o:setattr(o,'closed',False),lambda o:setattr(o,'quarantined',True),
                 lambda o:o.tasks.add(Done(False)),lambda o:o.tasks.add(Done(error=ValueError('CANARY'))),
                 lambda o:setattr(o.peers[0],'run_finished',False),lambda o:setattr(o.peers[0].socket,'connection_lost_waiter',Done(False)),lambda o:setattr(o.peers[0].session,'active',True),
                 lambda o:o.connections[0].update(cleanup_confirmed=False),lambda o:o.connections[0].update(pending_after_cleanup=False),
                 lambda o:setattr(o.relays[0],'open',True),lambda o:setattr(o.relays[0].server,'serving',True),
                 lambda o:setattr(o.relays[0].links[0][0],'fd',7),lambda o:setattr(o.relays[0].links[0][0]._protocol,'_closed',Done(False))]
        for index,change in enumerate(changes):
            with self.subTest(index=index):
                owner=Owner();change(owner)
                with self.assertRaises(m.Rejected):m.release_closed_history(owner)
                self.assertEqual(len(owner.peers),1);self.assertEqual(len(owner.relays),1)
                self.assertEqual(len(owner.connections),1);self.assertEqual(len(owner.relays[0].links),1)
                self.assertTrue(owner.tasks)
    def test_reset_setup_cleanup_and_pipe_io_counts_do_not_rewrite_legacy(self):
        account=m.ResetAccounting();relay=NS(network_errors=0)
        self.assertTrue(account.observe_reset(relay,'workload',lambda:True))
        self.assertTrue(account.observe_reset(relay,'connection_cleanup',lambda:True))
        account.pipe_error('connection_cleanup');relay.network_errors+=1
        def closed_writer_reset():relay.network_errors+=2;return False
        self.assertFalse(account.observe_reset(relay,'global_cleanup',closed_writer_reset))
        r=account.metadata(relay.network_errors)
        self.assertEqual(relay.network_errors,3);self.assertEqual(r['pipe_io_errors'],{'connection_cleanup':1})
        self.assertEqual(r['reset_setup_errors']['global_cleanup'],2);self.assertEqual(r['unclassified_legacy'],0)
        self.assertEqual(sum(r['reset_calls'].values()),3)
    def test_read_only_analysis_labels_snapshot_delta_not_external_network_faults(self):
        r=dict(layer='real_loopback_tls_tcp_relay_synthetic_asr_model_tts',cloud_enabled=False,device_executed=False,
               attempts=[dict(index=0,relay_network_errors=1)],connection_ledger=[dict(index=0,relay_network_errors=3)],
               connections_attempted=1,attempted=1,resource_trends=dict(backend_rss_bytes=dict(first=100,last=200)),resource_samples=[])
        path=self.root/'old';raw=json.dumps(r).encode();path.write_bytes(raw)
        with patch.object(m,'heavy_lock',side_effect=AssertionError('no lock')),patch.object(m.subprocess,'run',side_effect=AssertionError('no child')):
            result=m.analyze(path)
        self.assertEqual(path.read_bytes(),raw);self.assertEqual(result['counter_deltas'][0]['delta'],2)
        self.assertEqual(result['attribution'],'unknown');self.assertEqual(result['historical_syscall_cause'],'unproven')
    def test_defaults_and_invalid_arm_cannot_start_lock_or_worker(self):
        for args in (['short14','--output',str(self.root/'out')],['_child','--arm','retain_plain','--nonce','f'*32,'--artifact',str(self.root/'a')]):
            with patch.object(m,'run',side_effect=AssertionError('disabled')),patch.object(m,'heavy_lock',side_effect=AssertionError('no lock')),redirect_stdout(io.StringIO()):
                self.assertEqual(m.cli(args),2)
        with patch.object(m,'heavy_lock',side_effect=AssertionError('invalid before lock')):
            with self.assertRaises(m.Rejected):m.run(self.root/'bad','unknown')
    def test_parent_invalid_metadata_is_terminal_keeps_artifact_no_retry(self):
        @contextmanager
        def lock():yield 42
        buf=io.BytesIO()
        with tarfile.open(fileobj=buf,mode='w'):pass
        def child(args,**kwargs):
            Path(args[args.index('--artifact')+1]).write_text('synthetic artifact retained')
            return NS(stdout=b'{"format":1}')
        out=self.root/'out'
        with patch.object(m,'heavy_lock',lock),patch.object(m.subprocess,'check_output',return_value=buf.getvalue()),patch.object(m.subprocess,'run',side_effect=child) as calls:
            with self.assertRaises(m.Rejected):m.run(out)
        self.assertEqual(calls.call_count,1)
        self.assertEqual(json.loads((out/'result.json').read_text())['status'],'failed_or_unknown_stopped')
        self.assertEqual((out/'retain_plain-full-report.json').read_text(),'synthetic artifact retained')
    def test_allocation_sites_and_unsupported_weak_types_are_explicit_not_native_bytes(self):
        class Snapshot:
            def statistics(self,kind):return [NS(traceback=[NS(filename='/SECRET/ssl.py')],size=5),NS(traceback=[NS(filename='/SECRET/scripts/v2_tls_retention.py')],size=8)]
        result=m.python_allocations(Snapshot());self.assertEqual(result['ssl_python'],5);self.assertEqual(result['diagnostic'],8)
        self.assertNotIn('SECRET',json.dumps(result))
        weak=m.WeakObjects();weak.watch('ssl_object',object())
        self.assertEqual(weak.metadata()['unsupported_observations']['ssl_object'],1)
    def test_single_fourteen_parent_contract_accepts_each_explicit_arm_only_once(self):
        @contextmanager
        def lock():yield 42
        buf=io.BytesIO()
        with tarfile.open(fileobj=buf,mode='w'):pass
        def child(args,**kwargs):return semantic_fixture(args)
        for arm in m.ARMS:
            with patch.object(m,'heavy_lock',lock),patch.object(m.subprocess,'check_output',return_value=buf.getvalue()),patch.object(m.subprocess,'run',side_effect=child) as calls:
                r=m.run(self.root/arm,arm)
            self.assertEqual(calls.call_count,1);self.assertEqual(len(r['completed']),1)
            self.assertEqual(r['completed'][0]['attempted'],14);self.assertEqual(r['attribution'],'unknown')
