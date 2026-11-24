"""Synthetic integration tests of the actual V2 adapter and Session."""
import asyncio
import base64
import json
import unittest
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from backend.v2.session import Session
from backend.v2.voice import VoicePeer, WireError, decode


class ProgressTests(unittest.TestCase):
    def fresh(self):
        self.now = 0
        s = Session(lambda: self.now)
        s.begin_turn(); stream = s.bind_player('p')
        tx, ack = s.task('tts'), s.task('ack')
        s.drain_commands()
        self.assertTrue(s.send(tx, name='a', public='one', end=100, approved=True))
        self.assertTrue(s.ack(ack, player='p', stream=stream, segment='a', head=100))
        self.assertTrue(s.send(replace(tx, sequence=1), name='b', public='two', end=200, approved=True))
        return s, stream, ack

    def test_same_head_new_sequence_does_not_extend(self):
        s, stream, ack = self.fresh()
        for t in range(10, 60, 10):
            self.now = t; s.heartbeat()
        s.ack(replace(ack, sequence=1), player='p', stream=stream, segment='b', head=100)
        self.assertEqual(s.progress_deadline, 60)
        self.now = 60; s.heartbeat(); s.poll()
        self.assertIsNone(s.player)
        self.assertTrue(s.response_expired)
        self.assertEqual(s.drain_commands()[0][0], 'mute_flush')

    def test_partial_real_progress_extends(self):
        s, stream, ack = self.fresh()
        for t in range(10, 60, 10):
            self.now = t; s.heartbeat()
        self.assertFalse(s.ack(replace(ack, sequence=1), player='p', stream=stream, segment='b', head=150))
        self.assertEqual(s.progress_deadline, 110)
        self.now = 60; s.heartbeat(); s.poll()
        self.assertEqual(s.player, 'p')
        self.assertEqual(s.context()['heard'], ('one',))

    def test_late_cannot_revive_even_without_poll(self):
        s, stream, ack = self.fresh()
        for t in range(10, 61, 10):
            self.now = t; s.heartbeat()
        self.assertFalse(s.ack(replace(ack, sequence=1), player='p', stream=stream, segment='b', head=200))
        self.assertTrue(s.response_expired)
        self.assertEqual(s.context()['heard'], ('one',))

    def test_sends_never_extend_progress(self):
        s, stream, ack = self.fresh()
        self.now = 10; s.heartbeat()
        self.assertEqual(s.progress_deadline, 60)


class Socket:
    def __init__(self): self.sent = []
    async def send(self, raw): self.sent.append(json.loads(raw))


class Policy:
    def input(self, text): return text
    def segment(self, text): return text


class Providers:
    def __init__(self): self.closed = 0; self.context = None
    @asynccontextmanager
    async def recognize(self, rate):
        class Recognizer:
            async def write(self, pcm): pass
            async def finish(self): return 'synthetic intent'
        try: yield Recognizer()
        finally: self.closed += 1
    async def endpoint(self, text, context):
        return dict(completion='complete', meaning='new_turn')
    @asynccontextmanager
    async def answer(self, text, context):
        self.context = context
        async def sentences(): yield 'synthetic answer'
        try: yield sentences()
        finally: self.closed += 1
    @asynccontextmanager
    async def synthesize(self, text, rate):
        async def chunks():
            yield b'\x01\x00' * 240
            yield b'\x02\x00' * 240
        try: yield chunks()
        finally: self.closed += 1


class PeerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket, self.providers = Socket(), Providers()
        self.peer = VoicePeer(self.socket, self.providers, Policy())
        self.seq = 0
    async def event(self, kind, **fields):
        await self.peer.handle(json.dumps(dict(v=2, type=kind, epoch=self.peer.epoch, seq=self.seq, **fields)))
        self.seq += 1
    async def asyncTearDown(self):
        for task in (self.peer.generation, self.peer.recognition):
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    async def wait_for(self, kind):
        async with asyncio.timeout(1):
            while not any(e['type'] == kind for e in self.socket.sent):
                await asyncio.sleep(.001)
        return next(e for e in reversed(self.socket.sent) if e['type'] == kind)
    async def test_real_session_adapter_pcm_ack_and_fact(self):
        await self.event('advance', revision=1)
        await self.event('input', pcm=base64.b64encode(b'\x01\x00'*320).decode())
        await self.event('probe', revision=1)
        await self.wait_for('endpoint')
        await self.event('seal', revision=1)
        decision = await self.wait_for('decision')
        await self.peer.handle(json.dumps(dict(v=2, type='stop', epoch=1, seq=0, intent=decision['intent'])))
        self.seq = 1
        await self.event('bind', player='native-track')
        bound = await self.wait_for('bound')
        await self.wait_for('audio')
        packet = next(e for e in self.socket.sent if e['type'] == 'audio')
        self.assertEqual(self.peer.session.context()['heard'], ())
        identity = bound['identity']
        await self.event('ack', identity=identity, player='native-track', stream=bound['stream'],
                         segment=packet['segment'], head=packet['end'])
        async with asyncio.timeout(1):
            while len([e for e in self.socket.sent if e['type']=='audio']) < 2:
                await asyncio.sleep(.001)
        last = [e for e in self.socket.sent if e['type']=='audio'][-1]
        identity = dict(identity, sequence=1)
        await self.event('ack', identity=identity, player='native-track', stream=bound['stream'],
                         segment=last['segment'], head=last['end'])
        self.assertEqual(self.peer.session.context()['heard'], ('synthetic answer',))
        self.assertEqual(self.providers.context['heard'], ())
        await self.peer.generation
        self.assertEqual(self.providers.closed, 3)

    async def test_revoked_epoch_input_has_no_effect(self):
        await self.peer.handle(json.dumps(dict(v=2, type='stop', epoch=1, seq=0, intent='')))
        await self.peer.handle(json.dumps(dict(v=2, type='input', epoch=0, seq=0, pcm='AQI=')))
        self.assertEqual(self.peer.capture, bytearray())

    async def test_sequence_duplicate_and_unknown_fields_fail(self):
        await self.event('heartbeat')
        with self.assertRaises(WireError):
            await self.peer.handle(json.dumps(dict(v=2,type='heartbeat',epoch=0,seq=0)))
        with self.assertRaises(WireError):
            decode('{"v":2,"v":2,"type":"heartbeat","epoch":0,"seq":1}')
        with self.assertRaises(WireError):
            decode('{"v":2,"type":"heartbeat","epoch":0,"seq":1,"extra":0}')

    async def test_close_failure_quarantines(self):
        async def broken():
            try: await asyncio.Event().wait()
            finally: raise RuntimeError('synthetic close failure')
        self.peer.generation = asyncio.create_task(broken())
        await asyncio.sleep(0)
        with self.assertRaises(WireError): await self.peer.cancel_generation()
        self.assertTrue(self.peer.quarantined)

class EndpointRaceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = PeerTests.asyncSetUp
    asyncTearDown = PeerTests.asyncTearDown
    event = PeerTests.event
    wait_for = PeerTests.wait_for
    async def test_continuation_invalidates_prepared_intent(self):
        await self.event('advance', revision=1)
        await self.event('input', pcm=base64.b64encode(b'\x01\x00'*320).decode())
        await self.event('probe', revision=1)
        await self.wait_for('endpoint')
        await self.event('seal', revision=1)
        old = await self.wait_for('decision')
        await self.event('advance', revision=2)
        await self.peer.handle(json.dumps(dict(v=2,type='stop',epoch=1,seq=0,intent=old['intent'])))
        self.assertIsNone(self.peer.generation)
        self.assertFalse(any(e['type']=='open' for e in self.socket.sent))

    async def test_late_async_probe_ignored_and_continuation_samples_merged(self):
        release = asyncio.Event()
        calls = []
        async def endpoint(text, context):
            calls.append(text)
            if len(calls)==1: await release.wait()
            return dict(completion='complete',meaning='new_turn')
        self.providers.endpoint = endpoint
        await self.event('advance',revision=1)
        await self.event('input',pcm=base64.b64encode(b'\x01\x00'*320).decode())
        await self.event('probe',revision=1)
        async with asyncio.timeout(1):
            while not calls: await asyncio.sleep(.001)
        await self.event('advance',revision=2)
        await self.event('input',pcm=base64.b64encode(b'\x02\x00'*320).decode())
        await self.event('probe',revision=2)
        self.assertEqual(len(self.peer.capture),1280)
        release.set()
        result = await self.wait_for('endpoint')
        self.assertEqual(result['revision'],2)
        self.assertEqual(len(calls),2)
        self.assertFalse(any(e.get('revision')==1 for e in self.socket.sent))

    async def test_context_is_provided_for_same_short_word_without_local_shortcut(self):
        seen = []
        async def endpoint(text, context):
            seen.append(context)
            return dict(completion='complete',meaning='backchannel')
        self.providers.endpoint = endpoint
        self.peer.session.public = ['synthetic story in progress']
        await self.event('advance',revision=1)
        await self.event('input',pcm=base64.b64encode(b'\x01\x00'*320).decode())
        await self.event('probe',revision=1)
        await self.wait_for('endpoint')
        await self.event('seal',revision=1)
        result = await self.wait_for('decision')
        self.assertEqual(result['meaning'],'backchannel')
        self.assertEqual(seen[0]['heard'],('synthetic story in progress',))
        self.assertIsNone(self.peer.generation)
