"""Preparation fixtures only: no TLS, worker, cloud, lock or profile."""
import asyncio,copy,json,tempfile,unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch,AsyncMock
from scripts import v2_persistent_tls as m

METRICS=dict(backend_rss_bytes=100,backend_fds=7,backend_threads=1,asyncio_tasks=2)
def state(n=1):
    return dict(cleanup_confirmed=True,constructed=n,new_session=True,finished=True,active=False,quarantined=False,pending=0,retired=0,errors=0,heard=0,pending_audio=0,resources=dict(METRICS),game=None)
def fixture(rounds=3):
    rows=[]
    for index in range(rounds*14):
        fault=m.MATRIX[(index//2)%7] if index%2==0 else 'normal_close'
        status='interrupted' if fault=='playback_stop' else 'fault_injected' if fault in {'asr_rst','plan_rst','partial_rst','half_open'} else 'delivered'
        frames=0 if fault in {'asr_rst','plan_rst'} else 4 if status=='delivered' else 1
        row=dict(index=index,fault=fault,status=status,cleanup_confirmed=True,client_cleanup=True,service_cleanup=state(index+1),
            new_session=True,control=None,frames=frames,acks=frames,heard_before_close=1 if status=='delivered' else 0,
            rst_applied=True if status=='fault_injected' else None,pause_observed=True if fault in {'half_open','pause_resume'} else None,
            relay_bytes=dict(up=100,down=200),relay_buffer_observed_max=100,old_ack_checked=True if index else None,close_handshake_confirmed=status=='delivered')
        if index==0:row['continuous']=dict(same_connection=True,stop_recovered=True,old_ack_rejected=True,stop_pending=0,
            stop=dict(status='interrupted',heard_before=3,heard_after=3,pending=0),recovery=dict(status='delivered',mode='association',constructed=1),turns=[dict(mode=mode,status='delivered',delivered=True,constructed=1,state_hash='a'*64) for mode in ('story','adventure')],final=dict(constructed=1,game='association',pending_audio=0))
        rows.append(row)
    checkpoints=[dict(phase='before_warmup',elapsed=0,service=state(0),client=dict(METRICS)),dict(phase='after_warmup',elapsed=1,service=state(2),client=dict(METRICS))]
    checkpoints += [dict(phase='after_round_'+str(i+1),elapsed=i+2,service=state((i+1)*14),client=dict(METRICS)) for i in range(rounds)]
    return dict(format=1,source_sha='a'*40,seed=17,protocol_contract=m.CONTRACT,rounds_requested=rounds,status='collected_not_stability_verdict',cleanup_confirmed=True,service_exit=0,
        cloud_enabled=False,device_executed=False,gc_forced=False,service_pid=20,driver_pid=10,attempts=rows,connection_count=len(rows),checkpoints=checkpoints)

class Preparation(unittest.TestCase):
    def test_default_and_invalid_bounds_do_not_spawn_or_lock(self):
        with patch.object(m,'supervise',side_effect=AssertionError('no execution')):
            self.assertEqual(m.cli(['prepare']),2);self.assertEqual(m.cli(['prepare','--enable','--rounds','4']),2)
        with patch.object(m,'heavy_lock',side_effect=AssertionError('no lock')):
            with self.assertRaises(m.Rejected):m.supervise('unused',0)
    def test_one_to_three_rounds_exact_total_and_split_process_samples(self):
        for rounds in (1,2,3):m.validate_report(fixture(rounds),rounds,'a'*40)
        r=fixture();r['driver_pid']=r['service_pid']
        with self.assertRaises(m.Rejected):m.validate_report(r,3,'a'*40)
    def test_fault_delivery_cleanup_and_same_session_counterfactuals(self):
        changes=[lambda r:r['attempts'][2].update(rst_applied=False),lambda r:r['attempts'][8].update(pause_observed=False),
            lambda r:r['attempts'][3].update(frames=0,acks=0),lambda r:r['attempts'][3].update(old_ack_checked=False),
            lambda r:r['attempts'][3]['service_cleanup'].update(pending=1),lambda r:r['attempts'][3].update(cleanup_confirmed=False),
            lambda r:r['attempts'][0]['continuous']['turns'][0].update(mode='guess'),
            lambda r:r['attempts'][0]['continuous']['turns'][1].update(constructed=2),
            lambda r:r['attempts'][0]['continuous'].update(old_ack_rejected=False)]
        for i,change in enumerate(changes):
            with self.subTest(i=i):
                r=fixture();change(r)
                with self.assertRaises(m.Rejected):m.validate_report(r,3,'a'*40)
    def test_no_success_on_missing_or_invalid_resource_collection(self):
        for change in (lambda r:r['checkpoints'][1]['service']['resources'].update(backend_rss_bytes=None),
                       lambda r:r['checkpoints'][1]['client'].update(backend_fds=True),
                       lambda r:r['checkpoints'][1].update(elapsed=-1),
                       lambda r:r['checkpoints'][1]['service'].update(constructed=0)):
            r=fixture();change(r)
            with self.assertRaises(m.Rejected):m.validate_report(r,3,'a'*40)
    def test_supervisor_uses_existing_lock_and_one_persistent_driver_no_retry(self):
        @contextmanager
        def lock():yield 42
        class Process:
            pid=12345
            def __init__(self,args,**kwargs):
                self.args=args;self.kwargs=kwargs
                output=Path(args[args.index('--output')+1]);(output/'result.json').write_text(json.dumps(fixture()))
            def wait(self,timeout):return 0
        with tempfile.TemporaryDirectory() as d,patch.object(m,'heavy_lock',lock),patch.object(m.subprocess,'check_output',return_value='a'*40),patch.object(m.subprocess,'Popen',side_effect=Process) as spawn:
            report=m.supervise(Path(d)/'output',3)
            self.assertEqual(len(report['attempts']),42);self.assertEqual(spawn.call_count,1)
            self.assertTrue(spawn.call_args.kwargs['start_new_session']);self.assertEqual(spawn.call_args.kwargs['pass_fds'],(42,))
    def test_outer_timeout_is_failure_and_kills_only_owned_group(self):
        @contextmanager
        def lock():yield 42
        class Process:
            pid=12345
            def __init__(self,*args,**kwargs):self.calls=0
            def wait(self,timeout):
                self.calls+=1
                if self.calls==1:raise m.subprocess.TimeoutExpired('fixed',timeout)
                return -9
        with tempfile.TemporaryDirectory() as d,patch.object(m,'heavy_lock',lock),patch.object(m.subprocess,'check_output',return_value='a'*40),patch.object(m.subprocess,'Popen',side_effect=Process) as spawn,patch.object(m.os,'killpg') as kill:
            out=Path(d)/'output'
            with self.assertRaises(m.Rejected):m.supervise(out,3)
            self.assertEqual(spawn.call_count,1);kill.assert_called_once_with(12345,m.signal.SIGKILL)
            self.assertFalse(json.loads((out/'supervisor.json').read_text())['cleanup_confirmed'])

class Ownership(unittest.IsolatedAsyncioTestCase):
    def fake_peer(self):
        session=NS(active=False,pending=[],game={},head=0,context=lambda:dict(heard=[]))
        return NS(closed=True,socket=NS(connection_lost_waiter=asyncio.get_running_loop().create_future()),session=session,retired_tasks=set(),generation=None,recognition=None,visual_task=None,quarantined=False,sequence=0,epoch=0)
    async def test_only_confirmed_current_peer_released_no_completed_history(self):
        service=m.Service();peer=self.fake_peer();peer.socket.connection_lost_waiter.set_result(None);service.peer=peer
        with patch.object(m,'scalar_resources',return_value=METRICS),patch.object(m,'drain',new=AsyncMock(return_value=(True,set(),0))):
            r=await service.dispatch(dict(op='release'))
        self.assertTrue(r['ok']);self.assertIsNone(service.peer);self.assertFalse(hasattr(service,'peers'))
    async def test_unconfirmed_peer_retained_and_reconnect_configuration_denied(self):
        service=m.Service();peer=self.fake_peer();peer.socket.connection_lost_waiter.set_result(None);service.peer=peer
        with patch.object(m,'scalar_resources',return_value=METRICS),patch.object(m,'drain',new=AsyncMock(return_value=(False,set(),1))):
            r=await service.dispatch(dict(op='release'))
            self.assertFalse(r['ok']);self.assertIs(service.peer,peer);self.assertTrue(service.isolated)
            with self.assertRaises(m.Rejected):await service.dispatch(dict(op='configure',text_index=0,fault='normal_close'))
    async def test_retired_task_observed_then_discarded_without_history(self):
        service=m.Service()
        async def broken():raise ValueError('SYNTHETIC_PRIVATE_CANARY')
        task=asyncio.create_task(broken());service.track(task)
        await asyncio.wait({task});await asyncio.sleep(0)
        self.assertEqual(service.errors,1);self.assertEqual(service.retired,set())
        with patch.object(m,'scalar_resources',return_value=METRICS):self.assertNotIn('CANARY',json.dumps(service.state()))

class WireFixtures(unittest.IsolatedAsyncioTestCase):
    async def test_actual_wire_ack_binds_current_epoch_and_drops_stale_audio(self):
        class Socket:
            def __init__(self):self.sent=[]
            def __aiter__(self):
                self.events=iter([dict(type='audio',epoch=99),dict(type='bound',epoch=0,identity={'scope':'synthetic'}),
                    dict(type='audio',epoch=0,player='p',stream=1,segment=1,end=4800),dict(type='reply_end',epoch=0)])
                return self
            async def __anext__(self):
                try:return json.dumps(next(self.events))
                except StopIteration:raise StopAsyncIteration
            async def send(self,raw):self.sent.append(json.loads(raw))
        ws=Socket();ipc=NS(call=AsyncMock(side_effect=[dict(state=dict(state_hash='same')),dict(state=dict(state_hash='same'))]))
        wire=m.Wire(ws,ipc,'normal_close',{'identity':'old synthetic fixture'})
        await wire.receive()
        self.assertEqual(wire.frames,1);self.assertEqual(wire.acks,1);self.assertTrue(wire.old_checked);self.assertTrue(wire.delivered)
        self.assertEqual([v['type'] for v in ws.sent],['ack','ack'])
        self.assertEqual(ws.sent[-1]['identity'],dict(scope='synthetic',sequence=0))
    async def test_old_ack_mutation_rejects_before_current_ack(self):
        class Socket:
            def __init__(self):self.sent=[];self.once=False
            def __aiter__(self):return self
            async def __anext__(self):
                if self.once:raise StopAsyncIteration
                self.once=True;return json.dumps(dict(type='audio',epoch=0,player='p',stream=1,segment=1,end=4800))
            async def send(self,raw):self.sent.append(json.loads(raw))
        ws=Socket();ipc=NS(call=AsyncMock(side_effect=[dict(state=dict(state_hash='before')),dict(state=dict(state_hash='changed'))]))
        wire=m.Wire(ws,ipc,'normal_close',{'identity':'old synthetic fixture'})
        with self.assertRaises(m.Rejected):await wire.receive()
        self.assertEqual(wire.acks,0);self.assertEqual(len(ws.sent),1)
