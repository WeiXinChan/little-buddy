"""R99 production-path isolation and protected-source retention regressions.

Fixtures are legal synthetic strings/PCM. Guards are tested against adversarial
cancellation, never against user audio or a remote account.
"""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from backend.v2.session import Session
from backend.v2.voice import Operation, StaleOperation, VoicePeer, WireError
from backend.v2.companion import CompanionPolicy, UnifiedProviders, ModelError
from test_m05 import Model, Speech, Socket, plan


class Providers:
    def __init__(self, stage='finish', mode='swallow'):
        self.stage, self.mode = stage, mode
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancel_seen = False
        self.endpoint_calls = []
        self.recognize_calls = 0
        self.closed = 0

    async def wait(self, stage):
        if self.stage != stage:
            return
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancel_seen = True
            if self.mode == 'honor':
                raise
            if self.mode == 'swallow':
                return
            # Refuse to finish until the test explicitly confirms resource exit.
            while not self.release.is_set():
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    self.cancel_seen = True

    @asynccontextmanager
    async def recognize(self, rate):
        self.recognize_calls += 1
        await self.wait('enter')
        try:
            yield self
        finally:
            await self.wait('close')
            self.closed += 1

    async def write(self, pcm):
        await self.wait('write')

    async def finish(self):
        await self.wait('finish')
        return '旧参与者合成私事'

    async def endpoint(self, text, context):
        self.endpoint_calls.append((text, deepcopy(context)))
        await self.wait('endpoint')
        return dict(completion='complete', meaning='new_turn')


class Isolation(unittest.IsolatedAsyncioTestCase):
    def peer(self, provider):
        socket = Socket()
        peer = VoicePeer(socket, provider, CompanionPolicy())
        socket.peer = peer
        peer.input_budget.speech()
        return peer, socket

    async def replacement(self, peer):
        old = peer.session
        old.handoff()
        peer.session = Session(old.clock)
        peer.session.private_mode = True
        peer.session.record_input('新参与者合成私事', [])
        return deepcopy(peer.session.context())

    async def settle(self, peer, provider):
        provider.release.set()
        if peer.recognition is not None:
            await asyncio.gather(peer.recognition, return_exceptions=True)
        if peer.retired_tasks:
            await asyncio.wait(set(peer.retired_tasks), timeout=1)
        await asyncio.sleep(0)

    async def test_current_asr_and_endpoint_positive_pair(self):
        provider = Providers()
        peer, socket = self.peer(provider)
        provider.release.set()
        peer.recognition = asyncio.create_task(peer.analyze(b'\1\0', 0, 0))
        await peer.recognition
        self.assertEqual(len(provider.endpoint_calls), 1)
        self.assertEqual(peer.analysis[1], '旧参与者合成私事')
        self.assertTrue(any(e['type']=='endpoint' for e in socket.events))
        self.assertEqual(provider.closed, 1)

    async def test_every_asr_await_rechecks_same_epoch_revision_before_upstream(self):
        for stage in ('enter', 'write', 'finish', 'close'):
            for mode in ('honor', 'swallow', 'refuse'):
                with self.subTest(stage=stage, mode=mode):
                    provider = Providers(stage, mode)
                    peer, socket = self.peer(provider)
                    peer.recognition = asyncio.create_task(peer.analyze(b'\1\0', 0, 0))
                    await provider.started.wait()
                    before = await self.replacement(peer)
                    start = asyncio.get_running_loop().time()
                    try:
                        await peer.cancel_recognition()
                        elapsed = asyncio.get_running_loop().time()-start
                        self.assertLess(elapsed, .8)
                        self.assertEqual(peer.epoch, 0)
                        self.assertEqual(peer.revision, 0)
                        await self.settle(peer, provider)
                        self.assertEqual(provider.endpoint_calls, [])
                        self.assertEqual(peer.session.context(), before)
                        self.assertIsNone(peer.analysis)
                        self.assertFalse(any(e['type'] in {'endpoint','decision'} for e in socket.events))
                        if mode=='refuse':
                            self.assertTrue(peer.quarantined)
                            with self.assertRaises(WireError):
                                await peer.handle(json.dumps(dict(v=2,type='probe',epoch=0,seq=0,revision=0)))
                    finally:
                        await self.settle(peer, provider)

    async def test_endpoint_inflight_only_keeps_authorized_old_snapshot(self):
        for mode in ('honor','swallow','refuse'):
            with self.subTest(mode=mode):
                provider = Providers('endpoint', mode)
                peer, socket = self.peer(provider)
                peer.session.record_input('原参与者公开来源', [])
                peer.recognition = asyncio.create_task(peer.analyze(b'\1\0',0,0))
                await provider.started.wait()
                before = await self.replacement(peer)
                try:
                    await peer.cancel_recognition()
                    await self.settle(peer,provider)
                    self.assertEqual(len(provider.endpoint_calls),1)
                    sent_context = provider.endpoint_calls[0][1]
                    self.assertIn('原参与者公开来源',str(sent_context))
                    self.assertNotIn('新参与者合成私事',str(sent_context))
                    self.assertEqual(peer.session.context(),before)
                    self.assertIsNone(peer.analysis)
                    self.assertFalse(any(e['type']=='endpoint' for e in socket.events))
                finally:
                    await self.settle(peer,provider)

    async def test_scope_captured_before_coroutine_is_scheduled(self):
        provider=Providers();peer,_=self.peer(provider)
        deferred=peer.analyze(b'\1\0',0,0)
        before=await self.replacement(peer)
        peer.recognition=asyncio.create_task(deferred)
        await peer.recognition
        self.assertEqual(provider.recognize_calls,0)
        self.assertEqual(peer.session.context(),before)

    async def test_same_session_new_turn_also_revokes_old_request(self):
        provider=Providers('finish','swallow');peer,_=self.peer(provider)
        peer.recognition=asyncio.create_task(peer.analyze(b'\1\0',0,0))
        await provider.started.wait()
        peer.session.begin_turn();peer.session.drain_commands()
        peer.session.record_input('新轮次合成来源',[])
        before=deepcopy(peer.session.context())
        await peer.cancel_recognition()
        await self.settle(peer,provider)
        self.assertEqual(provider.endpoint_calls,[])
        self.assertEqual(peer.session.context(),before)

    async def test_old_finally_cannot_consume_new_owner_pending(self):
        provider=Providers('finish','refuse');peer,_=self.peer(provider)
        old_task=asyncio.create_task(peer.analyze(b'\1\0',0,0))
        peer.recognition=old_task
        await provider.started.wait()
        await self.replacement(peer)
        # New owner's pending work must remain intact when the old task ends.
        new_owner=asyncio.create_task(asyncio.sleep(.05))
        peer.recognition=new_owner
        pending=(b'\2\0',Operation(peer,0,0),new_owner)
        peer.next_probe=pending
        provider.release.set()
        await old_task
        self.assertIs(peer.next_probe,pending)
        self.assertIs(peer.recognition,new_owner)
        self.assertEqual(provider.endpoint_calls,[])
        await new_owner

    async def test_only_owning_finally_can_dispatch_valid_pending_revision(self):
        provider=Providers('finish','swallow');peer,_=self.peer(provider)
        old_task=asyncio.create_task(peer.analyze(b'\1\0',0,0))
        peer.recognition=old_task
        await provider.started.wait()
        peer.revision=1
        follow=Operation(peer,0,1)
        peer.next_probe=(b'\2\0',follow,old_task)
        provider.release.set();await old_task
        fresh_task=peer.recognition
        self.assertIsNot(fresh_task,old_task)
        await fresh_task
        self.assertEqual(len(provider.endpoint_calls),1)
        self.assertEqual(peer.analysis[0],1)

    async def test_wrong_guard_negative_control_reproduces_cross_session_dispatch(self):
        provider=Providers('finish','swallow');peer,_=self.peer(provider)
        original=Operation.ensure
        Operation.ensure=lambda operation:None  # in-memory mutant only
        try:
            peer.recognition=asyncio.create_task(peer.analyze(b'\1\0',0,0))
            await provider.started.wait()
            await self.replacement(peer)
            await peer.cancel_recognition()
            await self.settle(peer,provider)
            # Removing the guard demonstrably dispatches old text again. Context
            # remains tied to the old object, so it cannot borrow the new secret.
            self.assertEqual(len(provider.endpoint_calls),1)
            self.assertNotIn('新参与者合成私事',str(provider.endpoint_calls))
            self.assertIsNotNone(peer.analysis)
        finally:
            Operation.ensure=original
            await self.settle(peer,provider)


class GenerationProviders(Providers):
    def __init__(self,stage,mode):
        super().__init__(stage,mode)
        self.calls=[]
    async def plan(self,text,context):
        self.calls.append(('plan',deepcopy(context)))
        await self.wait('plan')
        return dict(action='continue',mode='chat',rules='',roles=[],secrets={},
                    sentences=['合成回应。'],anchors={})
    async def facts(self,text):
        self.calls.append(('facts',text));await self.wait('facts');return []
    async def safe(self,text,context):
        self.calls.append(('safe',deepcopy(context)));await self.wait('safe');return True
    @asynccontextmanager
    async def synthesize(self,text,rate):
        self.calls.append(('synthesize',text))
        await self.wait('synthesize')
        async def chunks():
            await self.wait('chunks')
            yield b'\1\0'*100
        yield chunks()


class GenerationIsolation(unittest.IsolatedAsyncioTestCase):
    async def test_each_generation_upstream_step_rejects_old_session_or_turn_after_cancel(self):
        for stage in ('plan','facts','safe','synthesize','chunks'):
            for mode in ('honor','swallow','refuse'):
                with self.subTest(stage=stage,mode=mode):
                    provider=GenerationProviders(stage,mode)
                    socket=Socket();peer=VoicePeer(socket,provider,CompanionPolicy());socket.peer=peer
                    peer.session.begin_turn();peer.session.drain_commands()
                    task=asyncio.create_task(peer.respond('旧参与者合成输入',0));peer.generation=task
                    await peer.handle(json.dumps(dict(v=2,type='bind',epoch=0,seq=0,player='old')))
                    await provider.started.wait()
                    old=peer.session;old.handoff()
                    peer.session=Session(old.clock);peer.session.private_mode=True
                    peer.session.record_input('新人合成秘密',[])
                    before=deepcopy(peer.session.context())
                    calls=len(provider.calls)
                    start=asyncio.get_running_loop().time()
                    try:
                        try:await peer.cancel_generation()
                        except WireError:self.assertTrue(peer.quarantined)
                        self.assertLess(asyncio.get_running_loop().time()-start,.8)
                        provider.release.set();await asyncio.gather(task,return_exceptions=True)
                        self.assertEqual(len(provider.calls),calls)
                        self.assertNotIn('新人合成秘密',str(provider.calls))
                        self.assertEqual(peer.session.context(),before)
                        self.assertFalse(any(e['type']=='audio' for e in socket.events))
                    finally:
                        provider.release.set();await asyncio.gather(task,return_exceptions=True)
                        if peer.retired_tasks:await asyncio.wait(set(peer.retired_tasks),timeout=1)
                        await asyncio.sleep(0)


class SourceMemory(unittest.TestCase):
    def source(self, text, dimension=None):
        item=dict(key='preference',start=0,end=len(text),value=text)
        if dimension is not None:item['dimension']=dimension
        return item

    def remember(self,session,text,dimension=None):
        session.begin_turn();session.drain_commands()
        session.record_input(text,[self.source(text,dimension)])

    def test_four_five_dimensions_and_unknown_dimensions_preserve_all_sources(self):
        for tagged in (False,True):
            s=Session(lambda:0)
            inputs=[('我喜欢猫','animal'),('我喜欢蓝色','color'),('我喜欢面条','food'),
                    ('我喜欢足球','sport'),('我喜欢下棋','activity')]
            for n,(text,dim) in enumerate(inputs):
                self.remember(s,text,dim if tagged else None)
                if n==3:self.assertIn('我喜欢猫',str(s.context()['facts']))
            for n in range(12):s.record_input(f'普通背景{n}',[])
            s.public=[f'背景{i}' for i in range(50)]
            self.assertTrue(s.compact(s.memory_snapshot(),[]))
            context=s.context()
            for text,_ in inputs:self.assertIn(text,str(context['facts']))
            self.assertNotIn('我喜欢猫',str(context['recent']))
            self.assertLess(len(json.dumps(context,ensure_ascii=False).encode()),65536)

    def test_same_dimension_correction_retains_propositions_and_other_dimensions(self):
        s=Session(lambda:0)
        for text,dim in [('我喜欢猫','animal'),('我喜欢蓝色','color'),
                         ('刚才说错了，我不喜欢猫，我喜欢狗','animal')]:
            self.remember(s,text,dim)
        for n in range(12):s.record_input(f'背景{n}',[])
        sources=list(s.context()['facts'].values())
        self.assertEqual({v['dimension'] for v in sources},{'animal','color'})
        self.assertTrue(all(v['evidence_only'] for v in sources))
        self.assertEqual(s.facts['public:preference']['source_text'],'刚才说错了，我不喜欢猫，我喜欢狗')
        self.assertIn('我喜欢蓝色',str(sources))
        self.assertIn('我喜欢猫',str(sources))

    def test_same_turn_sources_are_not_overwritten_by_turn_number_collision(self):
        s=Session(lambda:0)
        for text in ('我喜欢猫','我喜欢蓝色','我喜欢面条','我喜欢足球','我喜欢下棋'):
            s.record_input(text,[self.source(text)])
        self.assertEqual(len(s.facts),5)

    def test_two_dimensions_in_one_utterance_keep_both_provenance_spans(self):
        s=Session(lambda:0);text='我喜欢猫，也喜欢蓝色'
        s.record_input(text,[
            dict(key='preference',start=3,end=4,value='猫',dimension='animal'),
            dict(key='preference',start=8,end=10,value='蓝色',dimension='color')])
        facts=list(s.facts.values())
        self.assertEqual(len(facts),2)
        self.assertEqual({f['dimension'] for f in facts},{'animal','color'})
        self.assertTrue(all(f['value']==text[f['span'][0]:f['span'][1]] for f in facts))

    def test_actual_byte_capacity_reports_gap_without_evicting_unwithdrawn_sources(self):
        s=Session(lambda:0)
        for n in range(1500):
            text=f'我喜欢第{n}种合成动物'
            before=deepcopy((s.facts,s.source_archive))
            if not s.record_input(text,[self.source(text,'animal')]):
                self.assertEqual((s.facts,s.source_archive),before)
                self.assertIn('我喜欢第0种合成动物',str(s.context(query='第0种合成动物')))
                self.assertGreater(n,500)
                self.assertTrue(s.context()['memory']['capacity_limited'])
                self.assertIn(text,str(s.context()['recent']))
                self.assertTrue(s._fits())
                return
        self.fail('unified byte capacity was never enforced')

    def test_invalid_fact_does_not_partially_replace_existing_sources(self):
        s=Session(lambda:0);self.remember(s,'我喜欢猫','animal')
        before=deepcopy((s.facts,s.recent,s.memory_revision))
        for bad in (dict(key='preference',start=0,end=4,value='我喜欢狗'),
                    self.source('我喜欢蓝色','untrusted')):
            with self.assertRaises(ValueError):s.record_input('我喜欢蓝色',[self.source('我喜欢蓝色','color'),bad])
            self.assertEqual((s.facts,s.recent,s.memory_revision),before)

    def test_wrong_four_slot_negative_control_would_lose_animal_source(self):
        texts=('我喜欢猫','我喜欢蓝色','我喜欢面条','我喜欢足球','我喜欢下棋')
        good=Session(lambda:0)
        for text in texts:good.record_input(text,[self.source(text)])
        self.assertIn('我喜欢猫',str(good.facts))
        original=Session.record_input
        def wrong_four_slots(session,text,facts):
            original(session,text,facts)
            history=[k for k in session.facts if k.startswith('public:preference:history:')]
            for obsolete in history[:-3]:del session.facts[obsolete]
        Session.record_input=wrong_four_slots
        try:
            wrong=Session(lambda:0)
            for text in texts:wrong.record_input(text,[self.source(text)])
            for n in range(12):wrong.record_input(f'背景{n}',[])
            self.assertNotIn('我喜欢猫',str(wrong.context()))
        finally:
            Session.record_input=original
