import asyncio,json,unittest
from unittest.mock import patch
from backend.v2 import timing
from backend.v2.voice import Operation
from backend.v2.session import Session
from tests.v2 import test_m05 as old

class Timing(unittest.IsolatedAsyncioTestCase):
    make=old.Integration.make
    turn=old.Integration.turn
    async def test_disabled_allocates_no_trace_or_record(self):
        self.make()
        with patch.object(timing,'Trace',side_effect=AssertionError('disabled')):
            await self.turn('合成普通问候。')
        self.assertIsNone(timing._current.get());self.assertTrue(self.peer.session.public)
    async def test_parallel_scope_stages_bound_and_no_content(self):
        self.make();self.model.next_plan['sentences']=['合成第一句。','合成第二句。']
        trace=timing.Trace()
        with timing.observe(trace):await self.turn('合成普通问候。')
        rows=trace.report()['records'];stages=[r['stage'] for r in rows]
        self.assertIn('plan_start',stages);self.assertIn('facts_start',stages)
        self.assertIn('whole_end',stages);self.assertIn('segment_start',stages)
        self.assertLess(stages.index('whole_end'),stages.index('segment_start'))
        self.assertEqual(stages.count('first_audio_sent'),1)
        self.assertEqual({(r['epoch'],r['revision'],r['turn']) for r in rows},{(0,0,1)})
        self.assertNotIn('合成',json.dumps(trace.report(),ensure_ascii=False))
    async def test_observer_exception_does_not_change_delivery(self):
        self.make()
        def fail(row):raise RuntimeError('PRIVATE_BODY')
        trace=timing.Trace(fail)
        with timing.observe(trace):await self.turn('合成普通问候。')
        self.assertTrue(trace.observer_failed);self.assertTrue(self.peer.session.public)
        self.assertNotIn('PRIVATE_BODY',json.dumps(trace.report()))
    async def test_fixed_limit_and_closed_inherited_task(self):
        self.make();trace=timing.Trace();go=asyncio.Event()
        async def late():await go.wait();timing.mark('plan_end',self.peer)
        with timing.observe(trace):
            task=asyncio.create_task(late())
            for _ in range(140):timing.mark('compact_skipped',self.peer)
        go.set();await task
        self.assertEqual(len(trace.rows),128);self.assertTrue(trace.truncated)
    async def test_stale_epoch_revision_session_and_cancel_do_not_borrow_scope(self):
        for kind in ('epoch','revision','session','cancelled'):
            self.make();trace=timing.Trace();op=Operation(self.peer,self.peer.epoch,self.peer.revision)
            with timing.observe(trace):
                timing.mark('plan_start',self.peer,op)
                if kind=='session':self.peer.session=Session(self.peer.session.clock)
                elif kind=='cancelled':op.cancelled=True
                else:setattr(self.peer,kind,getattr(self.peer,kind)+1)
                timing.mark('plan_end',self.peer,op)
            self.assertEqual([r['stage'] for r in trace.rows],['plan_start']);self.assertEqual(trace.invalid_scope,1)
    async def test_safety_rejection_records_and_no_tts_audio(self):
        self.make();self.model.allowed=False;trace=timing.Trace()
        with timing.observe(trace):
            p=self.peer;p.session.begin_turn();p.session.drain_commands()
            p.generation=asyncio.create_task(p.respond('合成问候。',p.epoch))
            await p.handle(json.dumps(dict(v=2,type='bind',epoch=0,seq=0,player='synthetic')));await p.generation
        self.assertFalse(any(r['stage']=='tts_open' for r in trace.rows))
        self.assertTrue(any(r['outcome']=='safety_denied' for r in trace.rows))
        self.assertFalse(any(e['type']=='audio' for e in self.socket.events))
    async def test_deadline_release_and_stage_allowlist(self):
        self.make();trace=timing.Trace();self.peer.input_budget.speech(0);deadline=self.peer.input_budget.deadline
        with timing.observe(trace):
            timing.mark('ARBITRARY_BODY',self.peer)
            await self.turn('合成问候。')
        self.assertEqual(self.peer.input_budget.deadline,deadline)
        self.assertTrue(all(r['stage'] in timing.STAGES for r in trace.rows))

    async def test_unscoped_new_probe_cannot_borrow_same_peer_new_session(self):
        for change in ('session','connection'):
            self.make();trace=timing.Trace()
            with timing.observe(trace):
                timing.mark('probe_received',self.peer)
                if change=='session':self.peer.session=Session(self.peer.session.clock)
                else:self.peer.session.connection+=1
                timing.mark('probe_received',self.peer)
            self.assertEqual(len(trace.rows),1);self.assertEqual(trace.invalid_scope,1)

    async def test_old_or_invalid_ack_has_no_effective_ack(self):
        from dataclasses import asdict
        self.make();self.socket.acknowledge=False;p=self.peer;trace=timing.Trace()
        with timing.observe(trace):
            p.session.begin_turn();p.session.drain_commands()
            p.generation=asyncio.create_task(p.respond('合成问候。',p.epoch))
            try:
                await p.handle(json.dumps(dict(v=2,type='bind',epoch=0,seq=0,player='synthetic')))
                for _ in range(100):
                    audio=next((e for e in self.socket.events if e['type']=='audio'),None)
                    if audio:break
                    await asyncio.sleep(.001)
                self.assertIsNotNone(audio)
                event=dict(v=2,type='ack',epoch=0,seq=p.sequence+1,identity=asdict(p.ack_identity),player='wrong',stream=audio['stream'],segment=audio['segment'],head=audio['end'])
                await p.handle(json.dumps(event))
                self.assertFalse(any(r['stage']=='effective_ack' for r in trace.rows))
                event.update(player='synthetic',seq=p.sequence+1)
                await p.handle(json.dumps(event))
                self.assertEqual(sum(r['stage']=='effective_ack' for r in trace.rows),1)
            finally:await p.cancel_generation()
    async def test_expired_scope_does_not_clear_session_or_record(self):
        self.make();op=Operation(self.peer,self.peer.epoch,self.peer.revision);trace=timing.Trace()
        self.peer.session.expires=self.peer.session.clock()-1
        with timing.observe(trace):timing.mark('plan_end',self.peer,op)
        self.assertEqual(trace.rows,[]);self.assertTrue(self.peer.session.active)
    async def test_shared_provider_port_only_within_observed_v2_resource(self):
        from backend.timing import observer,mark
        from contextlib import asynccontextmanager
        self.make();op=Operation(self.peer,self.peer.epoch,self.peer.revision);trace=timing.Trace();outside=[]
        token=observer.set(lambda event,n:outside.append(event))
        @asynccontextmanager
        async def resource():
            mark('tts_socket_ready');mark('tts_task_ready');yield object()
        try:
            with timing.observe(trace):
                async with self.peer.owned_resource(op,resource):pass
            mark('outside')
        finally:observer.reset(token)
        self.assertEqual([r['stage'] for r in trace.rows],['tts_connected','tts_task_ready'])
        self.assertEqual(outside,['outside'])
    def test_release_selects_new_v2_module(self):
        from backend.v2.release import selected
        self.assertTrue(selected('backend/v2/timing.py'))
