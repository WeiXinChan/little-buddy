"""R97 paired regressions against actual VoicePeer, not a second session model."""
import asyncio
import base64
import json
import unittest
from backend.v2.voice import VoicePeer, WireError
from backend.v2.fixture import SyntheticPolicy, SyntheticProviders

PCM = base64.b64encode(b'\x01\x00'*320).decode()


class BudgetPathTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 0.0
        class Socket:
            def __init__(self): self.sent=[]
            async def send(self, raw): self.sent.append(json.loads(raw))
        self.socket=Socket(); self.providers=SyntheticProviders()
        self.peer=VoicePeer(self.socket,self.providers,SyntheticPolicy(),clock=lambda:self.now)
        self.seq=0
    async def event(self, kind, **fields):
        await self.peer.handle(json.dumps(dict(v=2,type=kind,epoch=self.peer.epoch,seq=self.seq,**fields)))
        self.seq+=1
    async def asyncTearDown(self):
        self.peer.closed=True
        for task in (self.peer.generation,self.peer.recognition):
            if task is not None:
                task.cancel(); await asyncio.gather(task,return_exceptions=True)
    async def input(self, revision=1, **fields):
        await self.event('advance',revision=revision)
        await self.event('input',pcm=PCM,**fields)
    async def complete(self):
        await self.event('probe',revision=self.peer.revision); await self.peer.recognition
        await self.event('seal',revision=self.peer.revision)
        intent=self.socket.sent[-1]['intent']
        await self.peer.handle(json.dumps(dict(v=2,type='stop',epoch=self.peer.epoch+1,seq=0,intent=intent)))
        self.seq=1
    async def test_fourteen_seconds_analysis_does_not_create_deadline_29(self):
        await self.input()
        async def endpoint(*_):
            self.now=14
            return dict(completion='complete',meaning='new_turn')
        self.providers.endpoint=endpoint
        await self.complete()
        self.assertEqual(self.peer.session.deadline,15)
        self.now=14.5; await self.event('heartbeat')
        self.now=16
        self.assertFalse(self.peer.session._output_live())
        self.assertTrue(self.peer.session.response_expired)
    async def test_capture_owner_and_wire_age_are_inside_the_same_budget(self):
        self.now=6
        await self.input(speech=True,age_ms=6000)
        await self.complete()
        self.assertEqual(self.peer.session.deadline,15)
        self.now=10; await self.event('heartbeat'); self.now=15
        self.assertFalse(self.peer.session._output_live())
    async def test_quiet_packets_and_seal_do_not_move_expression_boundary(self):
        await self.input(speech=True,age_ms=0)
        self.now=10; await self.event('input',pcm=PCM,speech=False,age_ms=0)
        await self.complete()
        self.assertEqual(self.peer.session.deadline,15)
        self.assertTrue(self.peer.session.retry(safe=True,idempotent=True))
        self.assertEqual(self.peer.session.deadline,15)
    async def test_real_continuation_updates_boundary_but_seal_does_not(self):
        await self.input(speech=True,age_ms=0)
        self.now=8; await self.input(revision=2,speech=True,age_ms=1000)
        self.now=12; await self.complete()
        self.assertEqual(self.peer.session.deadline,22)
    async def test_explicit_thinking_is_separately_accounted(self):
        await self.input()
        async def thinking(*_):
            self.now=4
            return dict(completion='thinking',meaning='thinking')
        self.providers.endpoint=thinking
        await self.event('probe',revision=1); await self.peer.recognition
        self.now=14
        async def complete(*_): return dict(completion='complete',meaning='new_turn')
        self.providers.endpoint=complete
        await self.complete()
        self.assertEqual(self.peer.input_budget.thinking_seconds,10)
        self.assertEqual(self.peer.session.deadline,25)
        self.now=14.5; await self.event('heartbeat'); self.now=26
        self.assertFalse(self.peer.session._output_live())
    async def test_negative_age_or_client_absolute_future_clock_cannot_extend(self):
        await self.event('advance',revision=1)
        with self.assertRaises(WireError):
            await self.event('input',pcm=PCM,speech=True,age_ms=-10000)
        self.assertIsNone(self.peer.input_budget.deadline)
        with self.assertRaises(WireError):
            await self.peer.handle(json.dumps(dict(v=2,type='input',epoch=0,seq=1,pcm=PCM,speech_at=999999999)))
        self.assertIsNone(self.peer.input_budget.deadline)
    async def test_exhaustion_during_asr_endpoint_cannot_be_sealed(self):
        await self.input()
        async def endpoint(*_):
            self.now=16
            return dict(completion='complete',meaning='new_turn')
        self.providers.endpoint=endpoint
        await self.event('probe',revision=1); await self.peer.recognition
        await self.event('seal',revision=1)
        self.assertIsNone(self.peer.prepared)
        self.assertFalse(any(e['type']=='open' for e in self.socket.sent))

class EffectivePlaybackBoundaryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=BudgetPathTests.asyncSetUp
    asyncTearDown=BudgetPathTests.asyncTearDown
    event=BudgetPathTests.event
    input=BudgetPathTests.input
    complete=BudgetPathTests.complete
    async def first_packet(self):
        await self.input()
        async def endpoint(*_):
            self.now=14
            return dict(completion='complete',meaning='new_turn')
        self.providers.endpoint=endpoint
        await self.complete()
        await self.event('bind',player='native-coordinate')
        async with asyncio.timeout(1):
            while not any(e['type']=='audio' for e in self.socket.sent): await asyncio.sleep(.001)
        bound=next(e for e in self.socket.sent if e['type']=='bound')
        packet=next(e for e in self.socket.sent if e['type']=='audio')
        self.now=14.5; await self.event('heartbeat')
        return bound,packet
    async def test_complete_effective_audio_before_budget_deadline_releases_first_wait(self):
        bound,packet=await self.first_packet();self.now=14.999
        await self.event('ack',identity=bound['identity'],player=bound['player'],stream=bound['stream'],
                         segment=packet['segment'],head=packet['end'])
        self.assertTrue(self.peer.session.response_confirmed)
        self.assertEqual(self.peer.session.context()['heard'],()) # First PCM does not invent a full sentence fact.
        self.now=16;self.assertTrue(self.peer.session._output_live())
    async def test_effective_ack_at_budget_deadline_cannot_revive_response(self):
        bound,packet=await self.first_packet();self.now=15
        await self.event('ack',identity=bound['identity'],player=bound['player'],stream=bound['stream'],
                         segment=packet['segment'],head=packet['end'])
        self.assertFalse(self.peer.session.response_confirmed)
        self.assertTrue(self.peer.session.response_expired)
        self.assertIsNone(self.peer.session.player)
        self.assertEqual(self.peer.session.context()['heard'],())
