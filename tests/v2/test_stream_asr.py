"""Real VoicePeer and production recognize/write/finish contract, offline controls.

No parallel fake implementation of the lease; test through wire handle/monitor.
"""
import asyncio,base64,json,time,unittest
from contextlib import asynccontextmanager
from backend.v2.voice import VoicePeer,WireError
from backend.v2.companion import CompanionPolicy
from backend.v2.session import Session
from backend.v2.live import parser

class Socket:
    def __init__(self):self.events=[];self.incoming=asyncio.Queue();self.closed=False
    async def send(self,raw):self.events.append(json.loads(raw))
    async def recv(self):return await self.incoming.get()
    async def close(self,*args):self.closed=True

class Port:
    def __init__(self):
        self.calls=[];self.ready=None;self.block_write=None;self.block_finish=None;self.block_close=None
        self.stubborn_write=False;self.stubborn_finish=False;self.fail=None;self.text='固定合成输入。'
        self.endpoint_result=dict(completion='complete',meaning='new_turn');self.endpoint_calls=[]
        self.endpoint_gate=None;self.stubborn_endpoint=False;self.on_write=None
    async def wait(self,gate,stubborn=False):
        if gate:
            while not gate.is_set():
                try:await gate.wait()
                except asyncio.CancelledError:
                    if not stubborn:raise
    @asynccontextmanager
    async def recognize(self,rate):
        assert rate==16000
        call=dict(pcm=bytearray(),writes=[],finish=0,closed=False);self.calls.append(call);owner=self
        class R:
            async def write(self,data):
                call['writes'].append(bytes(data))
                if owner.on_write:owner.on_write(bytes(data))
                await owner.wait(owner.block_write,owner.stubborn_write)
                if owner.fail=='write':raise OSError('synthetic_failure')
                call['pcm'].extend(data)
            async def finish(self):
                call['finish']+=1
                await owner.wait(owner.block_finish,owner.stubborn_finish)
                if owner.fail=='finish':raise OSError('synthetic_failure')
                return owner.text
        try:
            await self.wait(self.ready)
            if self.fail=='open':raise OSError('synthetic_failure')
            yield R()
        finally:
            await self.wait(self.block_close)
            call['closed']=True
    async def endpoint(self,text,context):
        self.endpoint_calls.append((text,context));await self.wait(self.endpoint_gate,self.stubborn_endpoint)
        return dict(self.endpoint_result)

class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.port=Port();self.socket=Socket();self.now=100.
        self.peer=VoicePeer(self.socket,self.port,CompanionPolicy(),clock=lambda:self.now,stream_asr=True)
    async def asyncTearDown(self):
        for name in ('ready','block_write','block_finish','block_close','endpoint_gate'):
            gate=getattr(self.port,name)
            if gate:gate.set()
        await self.peer.cancel_recognition()
        self.peer.clear_capture();self.peer.closed=True
        tasks=list(self.peer.retired_tasks)
        for t in tasks:
            if not t.done():t.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        self.peer.session.clear()
    async def send(self,kind,**fields):
        p=self.peer;epoch=fields.pop('epoch',p.epoch);seq=fields.pop('seq',p.sequence+1)
        await p.handle(json.dumps(dict(v=2,type=kind,epoch=epoch,seq=seq,**fields)))
    async def pcm(self,data=b'\1\0'*320,speech=True):
        await self.send('input',pcm=base64.b64encode(data).decode(),speech=speech,age_ms=0)
    async def begin(self):
        await self.send('wake');await self.send('advance',revision=1);await self.pcm()
    async def spin(self,predicate):
        async with asyncio.timeout(1):
            while not predicate():await asyncio.sleep(.001)
    async def probe(self):
        await self.send('probe',revision=self.peer.revision)
        await self.spin(lambda:self.peer.recognition_handoff is None and self.peer.recognition is not None and self.peer.recognition.done())
        await self.peer.recognition
    async def test_default_off_keeps_probe_snapshot(self):
        self.peer.stream_asr=False;await self.begin();await asyncio.sleep(.01)
        self.assertFalse(self.port.calls);await self.probe();self.assertEqual(len(self.port.calls),1)
    async def test_only_wake_then_real_speech_opens_once(self):
        await self.pcm(speech=False);await asyncio.sleep(.01);self.assertFalse(self.port.calls)
        await self.send('wake');await self.pcm();await asyncio.sleep(.01)
        self.assertFalse(self.port.calls) # retained pre-wake bytes never pre-uploaded
        self.peer.clear_capture();await self.pcm(speech=False);await asyncio.sleep(.01);self.assertFalse(self.port.calls)
        await self.pcm();await self.spin(lambda:len(self.port.calls)==1)
    async def test_no_wake_true_speech_never_preopens(self):
        await self.pcm();await asyncio.sleep(.01);self.assertFalse(self.port.calls)
    async def test_barewake_uses_existing_solo_no_asr(self):
        await self.send('wake');await self.send('wake_solo',age_ms=0)
        self.assertFalse(self.port.calls);self.assertTrue(self.peer.prepared)
    async def test_multiple_revisions_one_resource_current_probe_only_finish(self):
        await self.begin();await self.spin(lambda:len(self.port.calls)==1)
        for rev in range(2,7):
            await self.send('advance',revision=rev);await self.pcm(bytes([rev,0])*320)
        await self.spin(lambda:len(self.port.calls[0]['pcm'])==3840)
        self.assertEqual(len(self.port.calls),1);self.assertEqual(self.port.calls[0]['finish'],0)
        await self.probe();self.assertEqual(self.peer.analysis[0],6)
        self.assertEqual(self.port.calls[0]['finish'],1);self.assertTrue(self.port.calls[0]['closed'])
        self.assertEqual(len(self.port.calls),1)
    async def test_connecting_append_nonblocking_no_future_full_order(self):
        self.port.ready=asyncio.Event();await self.begin();await self.spin(lambda:len(self.port.calls)==1)
        expected=bytearray(self.peer.capture)
        for rev in range(2,5):
            start=time.monotonic();await self.send('advance',revision=rev)
            data=bytes([rev,0])*2000;await self.pcm(data);expected.extend(data)
            self.assertLess(time.monotonic()-start,.05)
        self.assertFalse(self.port.calls[0]['writes'])
        self.port.on_write=lambda data:self.assertLessEqual(len(self.port.calls[0]['pcm'])+len(data),len(self.peer.capture))
        self.port.ready.set();await self.probe()
        self.assertEqual(self.port.calls[0]['pcm'],expected);self.assertEqual(len(self.port.calls),1)
        self.assertTrue(all(len(b)<=6400 for b in self.port.calls[0]['writes']))
    async def test_probe_advance_before_worker_scheduled_restores_full_snapshot(self):
        self.port.ready=asyncio.Event();await self.begin();await self.spin(lambda:len(self.port.calls)==1)
        await self.send('probe',revision=1)
        await self.send('advance',revision=2);await self.pcm(b'\2\0'*320)
        self.port.ready.set();await self.probe()
        self.assertEqual(len(self.port.calls),2);self.assertEqual(self.port.calls[-1]['pcm'],b'\1\0'*320+b'\2\0'*320)
        self.assertEqual([e['revision'] for e in self.socket.events if e['type']=='endpoint'],[2])
    async def test_continuation_after_finish_is_snapshot_no_new_preopen(self):
        await self.begin();await self.probe();self.assertEqual(len(self.port.calls),1)
        await self.send('advance',revision=2);await self.pcm(b'\2\0'*320);await asyncio.sleep(.01)
        self.assertEqual(len(self.port.calls),1)
        await self.probe();self.assertEqual(len(self.port.calls),2)
        self.assertEqual(self.port.calls[1]['pcm'],b'\1\0'*320+b'\2\0'*320)
    async def test_same_revision_append_revokes_frozen_N(self):
        self.port.block_finish=asyncio.Event();await self.begin();await self.send('probe',revision=1)
        await self.spin(lambda:self.port.calls and self.port.calls[0]['finish']==1)
        await self.pcm(b'\2\0'*320);self.port.block_finish.set();await self.probe()
        self.assertEqual([e['revision'] for e in self.socket.events if e['type']=='endpoint'],[1])
        self.assertEqual(self.port.calls[0]['pcm'],b'\1\0'*320)
        self.assertEqual(self.port.calls[1]['pcm'],b'\1\0'*320+b'\2\0'*320)
    async def test_quiet_frames_after_probe_do_not_cancel_or_write_beyond_N(self):
        self.port.block_finish=asyncio.Event();await self.begin();await self.send('probe',revision=1)
        await self.spin(lambda:self.port.calls and self.port.calls[0]['finish']==1)
        for _ in range(6):await self.pcm(b'\0\0'*320,speech=False)
        self.assertEqual(len(self.port.calls),1);self.assertEqual(self.port.calls[0]['pcm'],b'\1\0'*320)
        self.assertEqual(len(self.peer.capture),7*640);self.assertIsNone(self.peer.recognition_handoff)
        self.port.block_finish.set();await self.peer.recognition
        self.assertEqual([e['revision'] for e in self.socket.events if e['type']=='endpoint'],[1])
    async def test_speech_after_detach_before_endpoint_invalidates_old_result(self):
        self.port.endpoint_gate=asyncio.Event();await self.begin();await self.send('probe',revision=1)
        await self.spin(lambda:bool(self.port.endpoint_calls));self.assertIsNone(self.peer.raw_asr)
        await self.pcm(b'\2\0'*320);self.port.endpoint_gate.set();await self.probe()
        self.assertEqual(len(self.port.calls),2);self.assertEqual(self.port.calls[1]['pcm'],b'\1\0'*320+b'\2\0'*320)
        self.assertEqual([e['revision'] for e in self.socket.events if e['type']=='endpoint'],[1])
    async def test_late_endpoint_result_cannot_publish(self):
        self.port.endpoint_gate=asyncio.Event();self.port.stubborn_endpoint=True
        await self.begin();await self.send('probe',revision=1);await self.spin(lambda:bool(self.port.endpoint_calls))
        await self.send('advance',revision=2);self.port.endpoint_gate.set();await self.pcm(b'\2\0'*320)
        await self.probe();self.assertEqual([e['revision'] for e in self.socket.events if e['type']=='endpoint'],[2])
    async def test_asr_exception_failure_no_fallback_retry(self):
        self.port.fail='open';await self.begin();await self.spin(lambda:bool(self.port.calls))
        await self.send('advance',revision=2);await self.pcm();await self.probe()
        self.assertEqual(len(self.port.calls),1);self.assertFalse(self.port.endpoint_calls)
        self.assertEqual([e['code'] for e in self.socket.events if e['type']=='failure'],['network'])
        self.assertFalse(any(e['type']=='decision' and e.get('meaning')=='unknown' for e in self.socket.events))
    async def test_empty_and_unknown_keep_existing_resolution_no_audio(self):
        await self.send('wake')
        for empty in (True,False):
            self.socket.events.clear();self.port.text='' if empty else '固定合成输入。'
            self.port.endpoint_result=dict(completion='complete',meaning='unknown')
            await self.send('advance',revision=self.peer.revision+1);await self.pcm()
            scope=dict(session=self.peer.session.session,turn=self.peer.session.turn,revision=self.peer.revision,epoch=self.peer.epoch)
            await self.probe()
            if not empty:await self.send('seal',revision=self.peer.revision)
            decisions=[e for e in self.socket.events if e['type']=='decision']
            self.assertEqual(len(decisions),1);self.assertEqual(decisions[0]['meaning'],'unknown')
            self.assertEqual({k:decisions[0][k] for k in ('revision','epoch')},{k:scope[k] for k in ('revision','epoch')})
            scopes=[e for e in self.socket.events if e['type']=='scope']
            self.assertEqual(len(scopes),1);self.assertEqual({k:scopes[0][k] for k in scope},scope)
            self.assertFalse(any(e['type'] in {'audio','failure'} for e in self.socket.events))
            self.assertIsNone(self.peer.input_budget.anchor);self.assertFalse(self.peer.capture)
            self.assertIsNone(self.peer.raw_asr);self.assertTrue(self.port.calls[-1]['closed'])
        # A genuine next natural input, with no new wake or synthetic ACK.
        self.port.text='后续固定输入。';self.port.endpoint_result=dict(completion='complete',meaning='new_turn')
        count=len(self.port.calls);await self.send('advance',revision=self.peer.revision+1);await self.pcm();await self.probe()
        self.assertEqual(len(self.port.calls),count+1);self.assertEqual(self.peer.analysis[3],'new_turn')
        self.assertFalse(self.peer.session.public)
    async def test_consumed_lease_endpoint_send_seal_race_does_not_revoke_operation(self):
        self.port.endpoint_result=dict(completion='complete',meaning='unknown')
        await self.begin();original=self.socket.send
        async def immediate(raw):
            await original(raw)
            event=json.loads(raw)
            if event['type']=='endpoint':await self.send('seal',revision=self.peer.revision)
        self.socket.send=immediate
        await self.probe()
        self.assertEqual([e['meaning'] for e in self.socket.events if e['type']=='decision'],['unknown'])
        self.assertIsNone(self.peer.raw_asr);self.assertTrue(self.port.calls[0]['closed'])
    async def test_budget_not_renewed_by_open_ready_advance_probe(self):
        await self.begin();budget=self.peer.input_budget;deadline=budget.deadline
        await self.spin(lambda:bool(self.port.calls));await self.send('advance',revision=2);await self.probe()
        self.assertIs(self.peer.input_budget,budget);self.assertEqual(budget.deadline,deadline)
    async def test_thinking_has_no_new_wallclock_limit(self):
        self.port.endpoint_result=dict(completion='thinking',meaning='thinking')
        await self.begin();await self.probe();self.assertIsNotNone(self.peer.input_budget.thinking_at)
        self.now+=21;self.peer.session.heartbeat();self.peer.input_budget.resume()
        self.assertGreater(self.peer.input_budget.remaining(),0);self.assertFalse(self.peer.quarantined)
    async def test_stop_revokes_before_probe_and_no_late_finish(self):
        self.port.ready=asyncio.Event();await self.begin();await self.spin(lambda:bool(self.port.calls))
        await self.send('stop',intent='',epoch=1,seq=0);self.port.ready.set()
        await self.spin(lambda:self.port.calls[0]['closed']);self.assertEqual(self.port.calls[0]['finish'],0)
        self.assertFalse(self.peer.capture)
    async def test_management_pause_resume_requires_new_wake(self):
        await self.begin();await self.spin(lambda:bool(self.port.calls));p=self.peer
        await self.send('management_pause',session=p.session.session,turn=p.session.turn,revision=2,epoch=1,seq=0)
        self.assertTrue(self.port.calls[0]['closed']);self.assertIsNone(p.raw_asr)
        pause=p.management_receipt
        await self.send('management_resume',session=p.session.session,turn=p.session.turn,revision=3,pause=pause,epoch=2,seq=0)
        await self.pcm();self.assertEqual(len(self.port.calls),1)
        await self.send('wake');await self.send('advance',revision=4);await self.pcm();await self.spin(lambda:len(self.port.calls)==2)
    async def test_private_session_connection_epoch_scope_changes_retire(self):
        for change in ('private','session','connection','epoch'):
            count=len(self.port.calls)
            await self.send('wake');await self.send('advance',revision=self.peer.revision+1);await self.pcm()
            await self.spin(lambda:len(self.port.calls)>count and len(self.port.calls[-1]['pcm'])>0)
            call=self.port.calls[-1];p=self.peer
            if change=='private':p.session.private_mode=not p.session.private_mode
            elif change=='session':p.session=Session(lambda:self.now)
            elif change=='connection':p.session.connection+=1
            else:p.epoch+=1
            await self.send('heartbeat');await self.spin(lambda:call['closed']);self.assertIsNone(p.raw_asr)
            self.assertEqual(call['finish'],0);p.clear_capture()
    async def test_expired_deadline_monitor_revokes_and_no_renew(self):
        await self.begin();await self.spin(lambda:bool(self.port.calls));deadline=self.peer.input_budget.deadline
        self.now=deadline;await asyncio.wait_for(self.peer.monitor(),1)
        self.assertTrue(self.port.calls[0]['closed']);self.assertEqual(self.peer.input_budget.deadline,deadline)
        self.assertTrue(any(e['type']=='failure' and e['code']=='timeout' for e in self.socket.events))
    async def test_ttl_and_heartbeat_expiry_release_raw_resource(self):
        await self.begin();await self.spin(lambda:bool(self.port.calls))
        self.peer.session.expires=self.now+.01;self.now+=.02
        await asyncio.wait_for(self.peer.monitor(),1)
        self.assertTrue(self.port.calls[0]['closed']);self.assertIsNone(self.peer.raw_asr)
    async def test_writer_ignores_cancel_quarantine_in_original_half_second(self):
        self.port.block_write=asyncio.Event();self.port.stubborn_write=True
        await self.begin();await self.spin(lambda:bool(self.port.calls) and bool(self.port.calls[0]['writes']))
        start=time.monotonic();self.peer.clear_capture();await asyncio.sleep(.53)
        self.assertTrue(self.peer.quarantined);self.assertLess(time.monotonic()-start,.65)
        self.assertEqual(len(self.port.calls),1)
    async def test_reader_finish_ignores_cancel_no_new_snapshot(self):
        self.port.block_finish=asyncio.Event();self.port.stubborn_finish=True
        await self.begin();await self.send('probe',revision=1)
        await self.spin(lambda:bool(self.port.calls) and self.port.calls[0]['finish']==1)
        await self.send('advance',revision=2);await self.pcm();await self.send('probe',revision=2)
        await asyncio.sleep(.53);self.assertTrue(self.peer.quarantined);self.assertEqual(len(self.port.calls),1)
    async def test_resource_close_unconfirmed_quarantines(self):
        self.port.block_close=asyncio.Event();await self.begin();await self.spin(lambda:bool(self.port.calls))
        self.peer.clear_capture();await asyncio.sleep(.53)
        self.assertTrue(self.peer.quarantined);self.assertEqual(len(self.port.calls),1)
    async def test_end_and_disconnect_release_without_extra_call(self):
        await self.begin();await self.spin(lambda:bool(self.port.calls));await self.send('end')
        self.assertTrue(self.port.calls[0]['closed']);self.assertIsNone(self.peer.raw_asr)
    async def test_heartbeat_expiry_revokes_and_releases(self):
        await self.begin();await self.spin(lambda:bool(self.port.calls))
        self.peer.session.heartbeat_deadline=self.now+.01;self.now+=.02
        await asyncio.wait_for(self.peer.monitor(),1)
        await self.spin(lambda:self.port.calls[0]['closed']);self.assertIsNone(self.peer.raw_asr)
    async def test_run_disconnect_finally_releases_early_writer(self):
        await self.begin();await self.spin(lambda:bool(self.port.calls))
        task=asyncio.create_task(self.peer.run());await asyncio.sleep(.01);task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        self.assertTrue(self.port.calls[0]['closed']);self.assertIsNone(self.peer.raw_asr)
        self.assertTrue(self.peer.closed);self.assertFalse(self.peer.quarantined)
    async def test_original_capacity_kept_no_extra_pcm_before_validation(self):
        await self.begin();await self.spin(lambda:bool(self.port.calls))
        data=b'\2\0'*3200
        while len(self.peer.capture)+len(data)<=640000:await self.pcm(data)
        remaining=640000-len(self.peer.capture)
        if remaining:await self.pcm(b'\2\0'*(remaining//2))
        with self.assertRaises(WireError):await self.pcm(b'\3\0')
        await self.probe();self.assertEqual(len(self.port.calls[0]['pcm']),640000)
        self.assertEqual(len(self.port.calls),1)
    async def test_actual_v2_speech_socket_reader_and_task_protocol(self):
        from websockets.asyncio.server import serve
        from backend.v2.speech import V2Speech
        received=[];actions=[];readers=[]
        async def handler(socket):
            first=json.loads(await socket.recv());ident=first['header']['task_id'];actions.append(first['header']['action'])
            async def event(kind,payload=None):await socket.send(json.dumps(dict(header=dict(task_id=ident,event=kind),payload=payload or {})))
            await event('task-started')
            async for value in socket:
                if isinstance(value,bytes):received.append(value)
                else:
                    actions.append(json.loads(value)['header']['action'])
                    await event('result-generated',{'output':{'sentence':{'sentence_end':True,'text':'固定合成输入。'}}})
                    await event('task-finished');await socket.wait_closed();return
        async with serve(handler,'127.0.0.1',0,close_timeout=.1) as server:
            speech=V2Speech(None,workspace='synthetic',region='cn-beijing',key='SYNTHETIC_ONLY',asr='fake',llm='qwen4-max',tts='fake',voice='fake')
            speech.ws_url='ws://127.0.0.1:'+str(server.sockets[0].getsockname()[1])
            @asynccontextmanager
            async def production_port(rate):
                async with speech.recognize(rate) as recognizer:
                    readers.append(recognizer.results);yield recognizer
            self.port.recognize=production_port
            await self.begin();await self.spin(lambda:len(received)>0)
            await self.send('advance',revision=2);await self.pcm(b'\2\0'*320);await self.probe()
            self.assertEqual(actions,['run-task','finish-task'])
            self.assertEqual(b''.join(received),b'\1\0'*320+b'\2\0'*320)
            self.assertTrue(all(t.done() for t in readers));self.assertFalse(speech.release_tasks)
            self.assertTrue(speech.last_release['confirmed']);self.assertEqual(self.peer.analysis[0],2)
    async def test_server_capability_flag_is_passed_only_when_enabled(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from backend.v2 import server
        captured=[];flags=[]
        class Peer:
            quarantined=False
            def __init__(self,*args,**kwargs):flags.append(kwargs)
            async def run(self):pass
        def serving(handler,*args,**kwargs):captured.append(handler);return object()
        socket=SimpleNamespace(request=SimpleNamespace(path='/v2/voice'))
        with patch.object(server,'VoicePeer',Peer),patch.object(server,'serve',serving):
            for flag in (False,True):
                server.voice_server('127.0.0.1',0,object(),'A'*32,self.port,CompanionPolicy(),stream_asr=flag)
                await captured[-1](socket)
        self.assertEqual(flags,[{},dict(stream_asr=True)])
    def test_cli_default_off_explicit_flag(self):
        values=[]
        for name in ('cert','key','token-file','device-scope','ca-file','tls-name','service-env','credential-directory','apk-contract'):
            values+=['--'+name,'synthetic']
        self.assertFalse(parser().parse_args(values).stream_asr)
        self.assertTrue(parser().parse_args(values+['--stream-asr']).stream_asr)

# Reuse the existing real full-duplex/ACK assertions, not a reimplementation.
from tests.v2 import test_post_solo_probe as protocol
class StreamPeer(VoicePeer):
    def __init__(self,*args,**kwargs):super().__init__(*args,stream_asr=True,**kwargs)
class StreamProtocol(protocol.ResolutionProtocol):
    peer_type=StreamPeer
class StreamTLS(protocol.ResolutionTLS):
    peer_type=StreamPeer
