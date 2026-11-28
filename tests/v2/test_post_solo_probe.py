"""Full production VoicePeer.run/wire ACK lifecycle; synthetic inputs only."""
import asyncio,base64,json,unittest,hashlib
from pathlib import Path
from contextlib import asynccontextmanager
from copy import deepcopy
from backend.v2.voice import VoicePeer
from backend.v2.companion import UnifiedProviders,CompanionPolicy
from backend.v2 import timing
from tests.v2.test_m05 import Model,Speech,plan

class Clock:
    def __init__(self):self.now=100.
    def __call__(self):return self.now
class Wire:
    def __init__(self):self.incoming=asyncio.Queue();self.outgoing=asyncio.Queue();self.events=[]
    async def recv(self):return await self.incoming.get()
    async def send(self,raw):
        e=json.loads(raw);self.events.append(e);await self.outgoing.put(e)
    async def close(self,*a):pass
class SpeechFixture(Speech):
    def __init__(self):self.mode='valid';self.calls=0
    @asynccontextmanager
    async def recognize(self,rate):
        self.calls+=1;owner=self
        class R:
            async def write(self,pcm):pass
            async def finish(self):
                if owner.mode=='asr_error':raise RuntimeError('SYNTHETIC_PRIVATE_EXCEPTION')
                return '' if owner.mode=='empty' else '我们接着想象小船。'
        yield R()
class EndpointModel(Model):
    def __init__(self):
        super().__init__(plan());self.endpoint_calls=0;self.block=False;self.fail=False
        self.entered=asyncio.Queue();self.release=asyncio.Event();self.cancelled=0;self.semantic_unknown=False;self.completion='complete'
    async def complete(self,instruction,data,*,schema=None):
        if 'completion' in schema.get('properties',{}):
            self.endpoint_calls+=1;await self.entered.put(self.endpoint_calls)
            if self.fail:raise RuntimeError('SYNTHETIC_PRIVATE_ENDPOINT')
            if self.block:
                try:await self.release.wait()
                except asyncio.CancelledError:self.cancelled+=1;raise
            if self.semantic_unknown:return json.dumps(dict(completion=self.completion,meaning='unknown'))
        return await super().complete(instruction,data,schema=schema)

# Immutable original implementation negative-control fixture, not current behavior.
from backend.v2 import voice as voice_module
raw=(Path(__file__).parent/'fixtures/code32_analyze_71c.py.txt').read_bytes()
assert hashlib.sha256(raw).hexdigest()=='ba92c0519554b50d25c547707cd88b80625ac85aab69a18566ffe2517f6a566d'
legacy_namespace=dict(vars(voice_module));exec(compile(raw,'code32_analyze_71c','exec'),legacy_namespace)
class BaselinePeer(VoicePeer):_analyze=legacy_namespace['_analyze']

class FullProtocol(unittest.IsolatedAsyncioTestCase):
    peer_type=BaselinePeer
    async def asyncSetUp(self):
        self.clock=Clock();self.wire=Wire();self.speech=SpeechFixture();self.model=EndpointModel()
        self.providers=UnifiedProviders(self.speech,self.model)
        self.epoch=0;self.seq=0;self.bound=None;self.acks=0
        self.trace=timing.Trace();self.ctx=timing.observe(self.trace);self.ctx.__enter__()
        await self.start_runner()
        await self.send('scope');await self.until('scope')
        await self.send('wake');await self.send('wake_solo',age_ms=0)
        await self.finish_reply()
        self.assertEqual(self.peer.session.turn,1)
        self.assertEqual(self.peer.session.deadline,0)
        self.assertTrue(self.peer.session.context()['heard'])
        self.first_session=self.peer.session
    async def start_runner(self):
        self.peer=self.peer_type(self.wire,self.providers,CompanionPolicy(),clock=self.clock)
        self.run=asyncio.create_task(self.peer.run())
    async def asyncTearDown(self):
        self.model.release.set()
        if not self.run.done():
            try:await self.send('end');await asyncio.wait_for(asyncio.shield(self.run),1.2)
            except BaseException:self.run.cancel();await asyncio.gather(self.run,return_exceptions=True)
        else:await asyncio.gather(self.run,return_exceptions=True)
        if self.peer.retired_tasks:await asyncio.gather(*list(self.peer.retired_tasks),return_exceptions=True)
        self.ctx.__exit__(None,None,None)
    async def send(self,kind,**fields):
        e=dict(v=2,type=kind,epoch=self.epoch,seq=self.seq,**fields);self.seq+=1
        await self.wire.incoming.put(json.dumps(e))
        # server processing can await bounded resource cleanup; this does not fake an ACK.
        await asyncio.sleep(0)
    async def heartbeat_processed(self,deadline):
        async with asyncio.timeout(1):
            while self.peer.session.heartbeat_deadline!=deadline:
                if self.run.done():
                    self.fail(str((self.peer.session.expiry_reason,self.peer.session.heartbeat_deadline,[e.get('code') for e in self.wire.events if e['type']=='failure'])))
                await asyncio.sleep(0)
    async def until(self,kind):
        async with asyncio.timeout(1):
            while True:
                e=await self.wire.outgoing.get()
                if e['type']==kind:return e
                self.assertNotEqual(e['type'],'failure')
    async def finish_reply(self):
        async with asyncio.timeout(2):
            while True:
                e=await self.wire.outgoing.get();kind=e['type']
                self.assertNotEqual(kind,'failure')
                if kind=='decision':
                    self.assertEqual(e['meaning'],'new_turn');self.epoch+=1;self.seq=0
                    await self.send('stop',intent=e['intent'])
                elif kind=='open':await self.send('bind',player='synthetic-'+str(self.epoch))
                elif kind=='bound':self.bound=e;self.acks=0
                elif kind=='audio':
                    await self.send('ack',identity=dict(self.bound['identity'],sequence=self.acks),player=self.bound['player'],stream=self.bound['stream'],segment=e['segment'],head=e['end']);self.acks+=1
                elif kind=='reply_end':
                    await self.peer.generation;return
    async def probe(self,rev,clock):
        self.clock.now=clock;await self.send('heartbeat');await self.send('advance',revision=rev)
        await self.send('input',pcm=base64.b64encode(b'\1\0'*320).decode(),speech=True,age_ms=0)
        await self.send('probe',revision=rev)
    async def test_solo_full_reply_then_next_probe_and_turn_are_not_stale(self):
        await self.probe(1,110)
        e=await self.until('endpoint');self.assertEqual(e['revision'],1)
        self.assertEqual(self.speech.calls,1);self.assertEqual(self.peer.session.turn,1)
        await self.send('seal',revision=1);await self.finish_reply()
        self.assertEqual(self.peer.session.turn,2);self.assertIs(self.peer.session,self.first_session)
        self.assertFalse(self.peer.quarantined)
    async def test_phone_shaped_repeated_probe_cancel_only_latest_endpoint_publishes(self):
        self.model.block=True
        for rev,t in enumerate((110.761,125.401,126.701,129.401,141.641,146.661),1):
            await self.probe(rev,t);await asyncio.wait_for(self.model.entered.get(),.3)
        self.model.release.set();e=await self.until('endpoint')
        self.assertEqual(e['revision'],6);self.assertEqual(self.model.cancelled,5)
        self.assertEqual(self.speech.calls,6)
        self.assertEqual([e['revision'] for e in self.wire.events if e['type']=='endpoint'],[6])
        await self.send('seal',revision=6);await self.finish_reply();self.assertEqual(self.peer.session.turn,2)
    async def assert_unknown_path(self,mode):
        self.speech.mode=mode;self.model.fail=mode=='endpoint_error'
        await self.probe(1,110)
        e=await self.until('decision');self.assertEqual(e['meaning'],'unknown')
        self.assertFalse(any(e['type']=='endpoint' for e in self.wire.events))
        self.assertIsNone(self.peer.analysis);self.assertIsNone(self.peer.prepared)
        self.assertTrue(self.peer.awaiting_input);self.assertEqual(self.peer.input_budget.deadline,125)
        # heartbeat/TTL stay valid: only the unchanged 15s expression boundary expires.
        self.clock.now=124;await self.send('heartbeat');await asyncio.sleep(.11)
        self.assertFalse(self.run.done())
        self.clock.now=125.006;failure=await self.until('failure')
        self.assertEqual(failure['code'],'timeout');await self.run
        self.assertTrue(self.peer.closed);self.assertFalse(self.peer.quarantined)
    async def test_empty_asr_can_reproduce_unknown_then_15s_without_endpoint(self):await self.assert_unknown_path('empty')
    async def test_asr_exception_can_reproduce_unknown_then_15s_without_endpoint(self):await self.assert_unknown_path('asr_error')
    async def test_endpoint_exception_can_reproduce_unknown_then_15s_without_endpoint(self):await self.assert_unknown_path('endpoint_error')

class ResolutionProtocol(FullProtocol):
    peer_type=VoicePeer
    async def test_empty_asr_can_reproduce_unknown_then_15s_without_endpoint(self):
        self.speech.mode='empty';before=len(self.peer.session.public)
        await self.probe(1,110);e=await self.until('decision')
        self.assertEqual(set(e),{'v','type','epoch','meaning','intent','revision'})
        self.assertEqual(e['meaning'],'unknown');self.assertFalse(self.peer.awaiting_input)
        self.assertEqual(self.peer.capture,bytearray());self.assertIsNone(self.peer.input_budget.anchor)
        self.assertEqual(self.peer.session.deadline,0);self.assertEqual(len(self.peer.session.public),before)
        self.clock.now=124;await self.send('heartbeat');await self.heartbeat_processed(139);self.clock.now=125.006
        await asyncio.sleep(.11);self.assertFalse(self.run.done())
        self.assertFalse(any(e['type']=='failure' for e in self.wire.events))
        count=self.speech.calls
        await self.send('input',pcm=base64.b64encode(b'\2\0'*320).decode(),speech=True,age_ms=0)
        await self.send('probe',revision=1);await asyncio.sleep(.01)
        self.assertEqual(self.speech.calls,count);self.assertIsNone(self.peer.input_budget.anchor)
        self.speech.mode='valid';await self.probe(2,125.1)
        endpoint=await self.until('endpoint');self.assertEqual(endpoint['revision'],2)
        await self.send('seal',revision=2);await self.finish_reply()
        self.assertEqual(self.peer.session.turn,2)
    async def assert_failure_path(self,mode):
        self.speech.mode=mode;self.model.fail=mode=='endpoint_error'
        await self.probe(1,110);e=await self.until('failure')
        self.assertEqual(e['code'],'voice');self.assertEqual(e['revision'],1)
        self.assertFalse({'analysis_outcome','analysis_stage'}&set(e))
        self.assertFalse(any(e['type']=='decision' and e.get('meaning')=='unknown' for e in self.wire.events))
        self.assertFalse(self.peer.awaiting_input);self.assertIsNone(self.peer.input_budget.anchor)
        self.assertFalse(self.peer.quarantined)
    async def test_asr_exception_can_reproduce_unknown_then_15s_without_endpoint(self):await self.assert_failure_path('asr_error')
    async def test_endpoint_exception_can_reproduce_unknown_then_15s_without_endpoint(self):await self.assert_failure_path('endpoint_error')
    async def test_normal_semantic_unknown_only_resolves_after_complete_seal(self):
        self.model.semantic_unknown=True
        await self.probe(1,110);await self.until('endpoint')
        self.assertTrue(self.peer.awaiting_input)
        await self.send('seal',revision=1);e=await self.until('decision')
        self.assertEqual(e['meaning'],'unknown');self.assertFalse(self.peer.awaiting_input)
        self.assertIsNone(self.peer.input_budget.anchor);self.assertEqual(self.peer.session.turn,1)
    async def test_incomplete_and_thinking_are_not_forced_sealed_or_resolved(self):
        self.model.semantic_unknown=True;self.model.completion='incomplete'
        await self.probe(1,110);e=await self.until('endpoint')
        self.assertEqual(e['completion'],'incomplete');self.assertTrue(self.peer.awaiting_input)
        self.assertIsNone(self.peer.input_resolution)
        await self.send('seal',revision=1);await asyncio.sleep(.01)
        self.assertFalse(any(e['type']=='decision' and e.get('revision')==1 for e in self.wire.events))
    async def test_quarantine_precedes_same_scope_latch(self):
        self.speech.mode='empty';await self.probe(1,110);await self.until('decision')
        self.peer.quarantined=True
        # Direct call observes the protocol rejection instead of terminating the receiver fixture.
        from backend.v2.voice import WireError
        with self.assertRaises(WireError):
            await self.peer.handle(json.dumps(dict(v=2,type='input',epoch=self.epoch,seq=self.peer.sequence+1,pcm='AQA=',speech=True,age_ms=0)))
        self.peer.quarantined=False

    async def test_unknown_revokes_unplayed_old_audio_and_rejects_old_ack(self):
        from dataclasses import asdict
        await self.probe(1,110);await self.until('endpoint');await self.send('seal',revision=1)
        async with asyncio.timeout(1):
            while True:
                e=await self.wire.outgoing.get()
                if e['type']=='decision':self.epoch+=1;self.seq=0;await self.send('stop',intent=e['intent'])
                elif e['type']=='open':await self.send('bind',player='unplayed-old')
                elif e['type']=='bound':bound=e
                elif e['type']=='audio':old=e;break
        self.speech.mode='empty';await self.probe(2,112);await self.until('decision')
        self.assertFalse(self.peer.session.pending);self.assertIsNone(self.peer.session.player)
        self.assertEqual(self.peer.session.deadline,0);self.assertIsNone(self.peer.generation)
        before=deepcopy(self.peer.session.context());old_head=self.peer.session.head
        await self.send('ack',identity=dict(bound['identity'],sequence=0),player=bound['player'],stream=bound['stream'],segment=old['segment'],head=old['end'])
        await asyncio.sleep(.01)
        self.assertEqual(self.peer.session.head,old_head);self.assertEqual(self.peer.session.context(),before)
        self.clock.now=124;await self.send('heartbeat');await self.heartbeat_processed(139);self.clock.now=127.006;await asyncio.sleep(.11)
        self.assertFalse(self.run.done());self.assertFalse(self.peer.session.response_expired)
        self.speech.mode='valid';await self.probe(3,127.1);await self.until('endpoint')
        await self.send('seal',revision=3);await self.finish_reply();self.assertEqual(self.peer.session.turn,3)

    async def test_stop_barrier_keeps_tail_latched_but_advance_admits_new_speech(self):
        self.speech.mode='empty';await self.probe(1,110);await self.until('decision')
        self.epoch+=1;self.seq=0;await self.send('stop',intent='')
        await self.send('scope');await self.until('scope')
        count=self.speech.calls
        await self.send('input',pcm='AQA=',speech=True,age_ms=0);await self.send('probe',revision=1)
        await self.send('scope');await self.until('scope')
        self.assertEqual(self.speech.calls,count);self.assertIsNone(self.peer.input_budget.anchor)
        self.speech.mode='valid';await self.probe(2,111);await self.until('endpoint')
        await self.send('seal',revision=2);await self.finish_reply()

class ResolutionTLS(ResolutionProtocol):
    """Same lifecycle/assertions over authenticated production loopback TLS."""
    async def start_runner(self):
        import tempfile,ssl,subprocess
        from unittest.mock import patch
        from websockets.asyncio.client import connect
        from backend.v2.server import voice_server
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
            '-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost',
            '-keyout',str(root/'key'),'-out',str(root/'cert')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(root/'cert',root/'key')
        trust=ssl.create_default_context(cafile=str(root/'cert'));done=asyncio.get_running_loop().create_future()
        def factory(socket,providers,policy):
            self.peer=self.peer_type(socket,providers,policy,clock=self.clock);original=self.peer.run
            async def run():
                try:await original()
                finally:
                    if not done.done():done.set_result(None)
            self.peer.run=run;return self.peer
        self.patch=patch('backend.v2.server.VoicePeer',factory);self.patch.start()
        self.server=await voice_server('127.0.0.1',0,tls,'A'*32,self.providers,CompanionPolicy())
        port=self.server.sockets[0].getsockname()[1]
        self.client=await connect(f'wss://localhost:{port}/v2/voice',ssl=trust,proxy=None,
            additional_headers={'Authorization':'Bearer '+'A'*32})
        async def pump_send():
            while True:await self.client.send(await self.wire.incoming.get())
        async def pump_recv():
            async for raw in self.client:
                e=json.loads(raw);self.wire.events.append(e);await self.wire.outgoing.put(e)
        self.pumps=[asyncio.create_task(pump_send()),asyncio.create_task(pump_recv())]
        async def wait():await done
        self.run=asyncio.create_task(wait())
    async def asyncTearDown(self):
        try:await super().asyncTearDown()
        finally:
            await self.client.close();self.server.close();await self.server.wait_closed()
            for task in self.pumps:task.cancel()
            await asyncio.gather(*self.pumps,return_exceptions=True)
            self.patch.stop();self.tmp.cleanup()

class ResolutionOwnership(unittest.IsolatedAsyncioTestCase):
    def peer(self):
        clock=Clock();peer=VoicePeer(Wire(),UnifiedProviders(SpeechFixture(),EndpointModel()),CompanionPolicy(),clock=clock)
        peer.input_budget.speech(0);peer.awaiting_input=True;peer.capture.extend(b'\1\0')
        return peer,clock
    async def test_scope_or_budget_replaced_during_release_cannot_resolve_new_input(self):
        from backend.v2.voice import Operation,StaleOperation
        from backend.v2.session import Session
        from backend.v2.budget import ResponseBudget
        for change in ('session','connection','turn','epoch','revision','private','budget','anchor','management'):
            with self.subTest(change=change):
                p,c=self.peer();op=Operation(p,p.epoch,p.revision);entered=asyncio.Event();release=asyncio.Event()
                async def output():
                    try:await asyncio.Event().wait()
                    except asyncio.CancelledError:entered.set();await release.wait()
                p.generation=asyncio.create_task(output());await asyncio.sleep(0)
                resolving=asyncio.create_task(p.finish_input_analysis(op,outcome='asr_empty'));await entered.wait()
                if change=='session':p.session=Session(clock=c)
                elif change=='connection':p.session.connection+=1
                elif change=='turn':p.session.turn+=1
                elif change=='epoch':p.epoch+=1
                elif change=='revision':p.revision+=1
                elif change=='private':p.session.private_mode=not p.session.private_mode
                elif change=='budget':p.input_budget=ResponseBudget(c);p.input_budget.speech(0)
                elif change=='anchor':c.now+=1;p.input_budget.speech(0)
                elif change=='management':p.session.management_paused=True
                budget=p.input_budget;release.set()
                with self.assertRaises(StaleOperation):await resolving
                self.assertIs(p.input_budget,budget);self.assertTrue(p.awaiting_input)
                self.assertEqual(p.capture,b'\1\0');self.assertFalse(p.socket.events)
    async def test_expired_input_cannot_become_unknown(self):
        from backend.v2.voice import Operation
        p,c=self.peer();op=Operation(p,0,p.revision);c.now=114;p.session.heartbeat();c.now=115
        with self.assertRaises(TimeoutError):await p.finish_input_analysis(op,outcome='asr_empty')
        self.assertTrue(p.awaiting_input);self.assertEqual(p.input_budget.deadline,115);self.assertFalse(p.socket.events)
    async def test_unconfirmed_output_exit_quarantines_within_original_half_second(self):
        from backend.v2.voice import Operation,WireError
        p,c=self.peer();release=asyncio.Event();entered=asyncio.Event()
        async def output():
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:entered.set();await release.wait()
        p.generation=asyncio.create_task(output());await asyncio.sleep(0)
        start=asyncio.get_running_loop().time()
        try:
            with self.assertRaises(WireError):await p.finish_input_analysis(Operation(p,0,p.revision),outcome='asr_empty')
            self.assertLess(asyncio.get_running_loop().time()-start,.7)
            self.assertTrue(p.quarantined);self.assertTrue(p.awaiting_input);self.assertFalse(p.socket.events)
        finally:release.set();await p.generation
    async def test_caller_cancel_cannot_publish_unknown(self):
        from backend.v2.voice import Operation
        p,c=self.peer();entered=asyncio.Event();release=asyncio.Event()
        async def output():
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:entered.set();await release.wait()
        p.generation=asyncio.create_task(output());await asyncio.sleep(0)
        task=asyncio.create_task(p.finish_input_analysis(Operation(p,0,p.revision),outcome='asr_empty'))
        await entered.wait();task.cancel();release.set()
        with self.assertRaises(asyncio.CancelledError):await task
        await p.generation;self.assertTrue(p.awaiting_input);self.assertFalse(p.socket.events)
    async def test_failed_release_cannot_emit_unknown_or_clear_input(self):
        from backend.v2.voice import Operation,WireError
        p,c=self.peer()
        async def output():
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:raise RuntimeError('SYNTHETIC_CLOSE_FAILURE')
        p.generation=asyncio.create_task(output());await asyncio.sleep(0)
        with self.assertRaises(WireError):await p.finish_input_analysis(Operation(p,0,p.revision),outcome='asr_empty')
        self.assertTrue(p.quarantined);self.assertTrue(p.awaiting_input);self.assertFalse(p.socket.events)
    async def test_expired_old_output_is_not_cleared_as_unknown(self):
        from backend.v2.voice import Operation,StaleOperation
        p,c=self.peer();p.session.deadline=101;p.session.player='synthetic-pending';op=Operation(p,0,p.revision);c.now=102
        with self.assertRaises(StaleOperation):await p.finish_input_analysis(op,outcome='asr_empty')
        self.assertTrue(p.session.response_expired);self.assertTrue(p.awaiting_input);self.assertFalse(p.socket.events)
    async def test_verified_safety_quota_network_keep_existing_failure_codes(self):
        from backend.v2.voice import Operation,VoiceFault
        from backend.v2.safety import SafetyFault
        for fault,code in ((SafetyFault('content_blocked'),'safety'),(VoiceFault('quota'),'quota'),(OSError(),'network'),(TimeoutError(),'timeout')):
            with self.subTest(code=code):
                p,c=self.peer();await p.finish_input_analysis(Operation(p,0,p.revision),failure=fault)
                terminal=p.socket.events[-1];self.assertEqual(terminal['type'],'failure');self.assertEqual(terminal['code'],code)
                self.assertFalse(any(e['type']=='decision' for e in p.socket.events));self.assertEqual('local_help' in terminal,code=='safety')
