"""Actual VoicePeer.run/wire; late old provider failures cannot own new input."""
import asyncio,unittest
from contextlib import asynccontextmanager
from backend.v2.voice import VoicePeer
from tests.v2 import test_post_solo_probe as protocol

class SupersededOutput(unittest.IsolatedAsyncioTestCase):
    peer_type=VoicePeer
    for name in ('asyncSetUp','asyncTearDown','start_runner','send','until','finish_reply','heartbeat_processed','probe'):
        locals()[name]=getattr(protocol.FullProtocol,name)
    async def test_old_tts_timeout_cannot_fail_new_revision(self):
        release=asyncio.Event();entered=asyncio.Event()
        @asynccontextmanager
        async def synthesize(text,rate):
            async def chunks():
                yield b'\1\0'*2400
                yield b'\1\0'*2400
                entered.set();await release.wait()
                raise TimeoutError('SYNTHETIC_OLD_OUTPUT')
            yield chunks()
        self.speech.synthesize=synthesize
        await self.probe(1,110);await self.until('endpoint')
        await self.send('seal',revision=1);decision=await self.until('decision')
        self.epoch+=1;self.seq=0;await self.send('stop',intent=decision['intent'])
        await self.until('open');await self.send('bind',player='old-output')
        await self.until('bound');await self.until('audio');await asyncio.wait_for(entered.wait(),1)
        old=self.peer.generation
        self.model.block=True
        await self.probe(2,114)
        async with asyncio.timeout(1):
            while self.model.endpoint_calls<2:await asyncio.sleep(0)
        deadline=self.peer.input_budget.deadline
        release.set();await asyncio.wait_for(asyncio.shield(old),1)
        self.assertFalse([e for e in self.wire.events if e['type']=='failure'])
        self.assertEqual(self.peer.input_budget.deadline,deadline)
        self.assertTrue(self.peer.awaiting_input)
        self.model.release.set();await self.until('endpoint')
        # The current expression can still seal, open and complete with actual ACKs.
        from tests.v2.test_m05 import Speech
        self.speech.synthesize=Speech().synthesize
        await self.send('seal',revision=2);await self.finish_reply()
        self.assertEqual(self.peer.session.turn,3)

    async def test_old_output_deadline_cannot_expire_fresh_input(self):
        entered=asyncio.Event();closing=asyncio.Event();closed=asyncio.Event()
        @asynccontextmanager
        async def synthesize(text,rate):
            async def chunks():
                yield b'\1\0'*2400;yield b'\1\0'*2400
                entered.set();await asyncio.Event().wait()
            try:yield chunks()
            finally:
                if getattr(self,'stall_close',False) or getattr(self,'advance_while_closing',False):
                    closing.set()
                    try:await closed.wait()
                    except asyncio.CancelledError:await closed.wait()
        self.speech.synthesize=synthesize
        await self.probe(1,110);await self.until('endpoint')
        await self.send('seal',revision=1);decision=await self.until('decision')
        self.epoch+=1;self.seq=0;await self.send('stop',intent=decision['intent'])
        await self.until('open');await self.send('bind',player='unacked-old-output')
        bound=await self.until('bound');audio=await self.until('audio');await asyncio.wait_for(entered.wait(),1)
        self.assertEqual(self.peer.session.deadline,125)
        limit=125.
        if getattr(self,'confirmed_old',False):
            await self.send('ack',identity=dict(bound['identity'],sequence=0),player=bound['player'],
                stream=bound['stream'],segment=audio['segment'],head=audio['end'])
            async with asyncio.timeout(1):
                while not self.peer.session.response_confirmed:await asyncio.sleep(0)
            self.assertEqual(self.peer.session.progress_deadline,170)
            for tick in (120,130,140,150,160):
                self.clock.now=tick;await self.send('heartbeat');await self.heartbeat_processed(tick+15)
            limit=170.
        self.model.block=True
        await self.probe(2,limit-2.654)
        async with asyncio.timeout(1):
            while self.model.endpoint_calls<2:await asyncio.sleep(0)
        deadline=self.peer.input_budget.deadline
        self.clock.now=limit;await self.send('heartbeat');await self.heartbeat_processed(limit+15)
        if getattr(self,'stall_close',False):
            await asyncio.wait_for(closing.wait(),1)
            async with asyncio.timeout(1):
                while not self.peer.quarantined:await asyncio.sleep(.01)
            failure=await self.until('failure');self.assertEqual(failure['code'],'voice')
            self.assertNotIn('session',failure) # unconfirmed cleanup grants no recovery
            closed.set();await asyncio.wait_for(asyncio.shield(self.run),1.5)
            self.assertEqual(self.peer.session.turn,2);return
        if getattr(self,'advance_while_closing',False):
            await asyncio.wait_for(closing.wait(),1)
            await self.probe(3,125.1)
            async with asyncio.timeout(1):
                while self.peer.input_budget.anchor!=125.1:await asyncio.sleep(0)
            deadline=self.peer.input_budget.deadline
            closed.set()
            async with asyncio.timeout(1):
                while self.peer.generation is not None and not self.peer.generation.done():await asyncio.sleep(0)
        await asyncio.sleep(.15)
        self.assertFalse([e for e in self.wire.events if e['type']=='failure'])
        self.assertFalse(self.run.done());self.assertEqual(self.peer.input_budget.deadline,deadline)
        self.assertTrue(self.peer.awaiting_input);self.assertIsNone(self.peer.session.player)
        self.assertEqual(self.peer.session.deadline,0)
        public=list(self.peer.session.public)
        await self.send('ack',identity=dict(bound['identity'],sequence=0),player=bound['player'],
            stream=bound['stream'],segment=audio['segment'],head=audio['end'])
        await asyncio.sleep(0)
        self.assertFalse(self.peer.session.response_expired);self.assertEqual(self.peer.session.public,public)
        if getattr(self,'expire_current',False):
            self.clock.now=deadline;await self.send('heartbeat')
            failure=await self.until('failure');self.assertEqual(failure['code'],'timeout')
            self.assertEqual(self.peer.input_budget.deadline,deadline);return
        self.model.release.set();await self.until('endpoint')
        from tests.v2.test_m05 import Speech
        self.speech.synthesize=Speech().synthesize
        await self.send('seal',revision=self.peer.revision);await self.finish_reply()
        self.assertEqual(self.peer.session.turn,3)

    async def test_retiring_old_output_does_not_extend_current_input(self):
        self.expire_current=True
        await self.test_old_output_deadline_cannot_expire_fresh_input()

    async def test_old_provider_ignoring_close_quarantines_without_recovery(self):
        self.stall_close=True
        await self.test_old_output_deadline_cannot_expire_fresh_input()

    async def test_new_revision_during_old_cleanup_keeps_current_capture_and_budget(self):
        self.advance_while_closing=True
        await self.test_old_output_deadline_cannot_expire_fresh_input()

    async def test_failure_scope_waits_for_fact_prefetch_close_proof(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def facts(text):
            entered.set()
            try:await release.wait()
            except asyncio.CancelledError:await release.wait()
            return []
        async def plan(*args,**kwargs):
            await entered.wait();raise RuntimeError('SYNTHETIC_PLAN_FAILURE')
        self.peer.providers.facts=facts;self.peer.providers.plan=plan
        await self.probe(1,110);await self.until('endpoint')
        await self.send('seal',revision=1);decision=await self.until('decision')
        self.epoch+=1;self.seq=0;await self.send('stop',intent=decision['intent'])
        await self.until('open');await self.send('bind',player='prefetch-held')
        await self.until('bound');failure=await self.until('failure')
        self.assertTrue(self.peer.quarantined);self.assertEqual(failure['code'],'voice')
        self.assertNotIn('session',failure)
        release.set();await asyncio.wait_for(asyncio.shield(self.run),1.5)

    async def test_old_60s_progress_expiry_cannot_fail_current_input(self):
        self.confirmed_old=True
        await self.test_old_output_deadline_cannot_expire_fresh_input()

    async def test_new_input_before_response_worker_starts_keeps_original_owner(self):
        start=asyncio.Event();original=self.peer._respond
        async def delayed(text,epoch,operation):
            await start.wait();return await original(text,epoch,operation)
        self.peer._respond=delayed
        await self.probe(1,110);await self.until('endpoint')
        await self.send('seal',revision=1);decision=await self.until('decision')
        self.epoch+=1;self.seq=0;await self.send('stop',intent=decision['intent'])
        await self.until('open');await self.send('bind',player='not-started-output');await self.until('bound')
        self.model.block=True;await self.probe(2,122.346)
        async with asyncio.timeout(1):
            while self.model.endpoint_calls<2:await asyncio.sleep(0)
        deadline=self.peer.input_budget.deadline
        old=self.peer.generation;start.set();await asyncio.wait_for(asyncio.shield(old),1)
        self.assertEqual(self.peer.response_scope[4],1)
        self.clock.now=125;await self.send('heartbeat');await self.heartbeat_processed(140)
        await asyncio.sleep(.15)
        self.assertFalse([e for e in self.wire.events if e['type']=='failure'])
        self.assertEqual(self.peer.input_budget.deadline,deadline)
        self.model.release.set();await self.until('endpoint')
        await self.send('seal',revision=2);await self.finish_reply();self.assertEqual(self.peer.session.turn,3)

    async def test_expiry_during_prefetch_close_cannot_grant_voice_recovery(self):
        entered=asyncio.Event();closing=asyncio.Event();release=asyncio.Event()
        async def facts(text):
            entered.set()
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:closing.set();await release.wait()
            return []
        async def plan(*args,**kwargs):
            await entered.wait();raise RuntimeError('SYNTHETIC_PLAN_FAILURE')
        self.peer.providers.facts=facts;self.peer.providers.plan=plan;self.peer.session.ttl=5
        await self.probe(1,110);await self.until('endpoint')
        await self.send('seal',revision=1);decision=await self.until('decision')
        self.epoch+=1;self.seq=0;await self.send('stop',intent=decision['intent'])
        await self.until('open');await self.send('bind',player='expiry-during-close');await self.until('bound')
        await asyncio.wait_for(closing.wait(),1)
        self.clock.now=115;release.set()
        ended=await self.until('session_end');self.assertEqual(ended['reason'],'session_expired')
        self.assertFalse([e for e in self.wire.events if e['type']=='failure'])

    async def test_current_quality_rejection_has_exact_scope_and_zero_audio(self):
        from backend.v2.review import ReviewDecision
        async def rejected(*args,**kwargs):return ReviewDecision(True,False)
        self.peer.providers.review=rejected
        before=len(self.wire.events)
        await self.probe(1,110);await self.until('endpoint')
        await self.send('seal',revision=1);decision=await self.until('decision')
        self.epoch+=1;self.seq=0;await self.send('stop',intent=decision['intent'])
        opened=await self.until('open');await self.send('bind',player='quality-rejected')
        await self.until('bound');failure=await self.until('failure')
        self.assertEqual(failure,dict(v=2,type='failure',epoch=self.epoch,code='voice',
            session=opened['session'],turn=opened['turn'],revision=1))
        self.assertFalse(any(e['type']=='audio' for e in self.wire.events[before:]))
        self.assertEqual(self.peer.last_failure['kind'],'QualityFault')
        self.assertFalse(self.peer.quarantined)

class StreamingSupersededOutput(SupersededOutput):
    @staticmethod
    def peer_type(*args,**kwargs):return VoicePeer(*args,**kwargs,stream_asr=True)

class SharedCancellation(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_retirement_and_stop_share_one_half_second(self):
        from backend.v2.voice import WireError
        peer=VoicePeer(protocol.Wire(),object(),object(),clock=protocol.Clock())
        entered=asyncio.Event();release=asyncio.Event();cancels=[]
        async def stubborn():
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancels.append(1);entered.set()
                try:await release.wait()
                except asyncio.CancelledError:cancels.append(1);await release.wait()
        old=asyncio.create_task(stubborn());await asyncio.sleep(0)
        start=asyncio.get_running_loop().time()
        first=asyncio.create_task(peer.cancel_generation_task(old));await entered.wait()
        await asyncio.sleep(.15)
        second=asyncio.create_task(peer.cancel_generation_task(old))
        results=await asyncio.gather(first,second,return_exceptions=True)
        elapsed=asyncio.get_running_loop().time()-start
        self.assertTrue(all(isinstance(r,WireError) for r in results))
        self.assertLess(elapsed,.65);self.assertEqual(cancels,[1]);self.assertTrue(peer.quarantined)
        release.set();await old;await asyncio.sleep(0)
        self.assertFalse(peer.generation_cancel_deadlines)
