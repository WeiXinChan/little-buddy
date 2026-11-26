"""Controlled-clock actual stop/monitor/run; no production TTL widening."""
import asyncio
import json
import unittest
from unittest.mock import patch
from backend.v2.voice import WireError
from backend.v2.companion import UnifiedProviders
from scripts import v2_soak as soak

class StopIdle(unittest.IsolatedAsyncioTestCase):
    async def make(self,run=False):
        t=soak.BackendTransport(UnifiedProviders(soak.OfflineSpeech(),soak.OfflineModel()));p=t.peer
        self.now=[100.];p.session.clock=lambda:self.now[0];p.session.expires=1000.;p.session.heartbeat_deadline=1000.
        self.addAsyncCleanup(t.close)
        if run:
            async def controlled_heartbeat():await asyncio.Future() # clock fixture pre-establishes valid heartbeat until1000
            t.heartbeat=controlled_heartbeat;t.start()
        return t,p

    async def test_root_monitor_counterexample_stopped_deadline_released_without_ttl_change(self):
        t,p=await self.make();p.session.begin_turn();await p.commands();deadline=p.session.deadline
        expires,heartbeat=p.session.expires,p.session.heartbeat_deadline
        await p.handle(json.dumps(dict(v=2,type='stop',epoch=1,seq=0,intent='synthetic-stop')))
        self.assertEqual(p.session.deadline,0);self.assertEqual(p.session.progress_deadline,0)
        self.assertEqual((p.session.expires,p.session.heartbeat_deadline),(expires,heartbeat))
        self.now[0]=deadline+.01;monitor=asyncio.create_task(p.monitor())
        try:
            await asyncio.sleep(.12);self.assertFalse(monitor.done());self.assertFalse(p.session.response_expired)
        finally:monitor.cancel();await asyncio.gather(monitor,return_exceptions=True)

    async def test_actual_run_remains_connected_after_old_deadline_then_next_turn_delivers(self):
        t,p=await self.make(run=True);p.session.begin_turn();await p.commands();deadline=p.session.deadline
        await t.command('stop',intent='synthetic-stop')
        for _ in range(100):
            if p.epoch==1 and getattr(p,'settling_stop',None) is None:break
            await asyncio.sleep(.001)
        self.now[0]=deadline+.01
        await asyncio.sleep(.12);self.assertFalse(p.closed)
        result=await t.attempt('轮流说红色水果。','normal')
        self.assertTrue(result['delivered']);self.assertFalse(p.closed)

    async def test_six_scenarios_with_controlled_thirty_second_intervals_same_session(self):
        t,p=await self.make(run=True);identity=p.session.session;statuses=[]
        for index,(_,text,mode) in enumerate(soak.SCENARIOS):
            self.now[0]=100+30*index;p.session.heartbeat_deadline=self.now[0]+15 # injected valid heartbeat boundary
            result=await t.attempt(text,mode);statuses.append(result['interrupted'] or result['delivered'])
            if mode in {'interrupt','drop'}:
                for _ in range(100):
                    if p.settling_stop is None:break
                    await asyncio.sleep(.001)
                self.assertEqual(p.session.deadline,0)
                self.now[0]+=15.01;p.session.heartbeat_deadline=self.now[0]+15
                await asyncio.sleep(.12);self.assertFalse(p.closed)
        self.assertTrue(all(statuses));self.assertEqual(p.session.session,identity)

    async def test_cancel_crossing_deadline_waits_confirmation_then_idles(self):
        t,p=await self.make();p.session.begin_turn();await p.commands();gate=asyncio.Event();entered=asyncio.Event()
        async def old():
            try:await asyncio.Future()
            except asyncio.CancelledError:entered.set();await gate.wait()
        p.generation=asyncio.create_task(old());await asyncio.sleep(0)
        stop=asyncio.create_task(p.handle(json.dumps(dict(v=2,type='stop',epoch=1,seq=0,intent='stop'))))
        await entered.wait();self.now[0]=115.01;monitor=asyncio.create_task(p.monitor())
        try:
            await asyncio.sleep(.12);self.assertFalse(monitor.done());self.assertEqual(p.session.deadline,115)
            gate.set();await stop;self.assertEqual(p.session.deadline,0)
        finally:gate.set();monitor.cancel();await asyncio.gather(monitor,return_exceptions=True);await stop

    async def test_new_revision_prepared_or_player_scope_during_cancel_is_not_cleared(self):
        for change in ('revision','prepared','turn'):
            t,p=await self.make();p.session.begin_turn();await p.commands();gate=asyncio.Event();entered=asyncio.Event()
            async def old():
                try:await asyncio.Future()
                except asyncio.CancelledError:entered.set();await gate.wait()
            p.generation=asyncio.create_task(old());await asyncio.sleep(0)
            stop=asyncio.create_task(p.handle(json.dumps(dict(v=2,type='stop',epoch=1,seq=0,intent='stop'))));await entered.wait()
            if change=='revision':p.revision+=1
            elif change=='prepared':p.prepared=('new',119.,'new-intent',p.revision)
            else:p.session.begin_turn()
            p.session.deadline=119.;p.session.progress_deadline=120.;p.session.response_confirmed=True
            gate.set();await stop
            self.assertEqual(p.session.deadline,119.);self.assertEqual(p.session.progress_deadline,120.);self.assertTrue(p.session.response_confirmed)
            if change=='prepared':self.assertEqual(p.prepared[2],'new-intent')

    async def test_unconfirmed_old_resource_and_expired_session_do_not_become_idle_live(self):
        t,p=await self.make();p.session.begin_turn();deadline=p.session.deadline
        async def failed():p.quarantined=True;raise WireError('synthetic unconfirmed')
        with patch.object(p,'cancel_generation',failed):
            with self.assertRaises(WireError):await p.handle(json.dumps(dict(v=2,type='stop',epoch=1,seq=0,intent='stop')))
        self.assertEqual(p.session.deadline,deadline);self.assertTrue(p.quarantined)
        t,p=await self.make();p.session.begin_turn();self.now[0]=p.session.expires
        await p.handle(json.dumps(dict(v=2,type='stop',epoch=1,seq=0,intent='stop')))
        self.assertFalse(p.session.active)

    async def test_prepared_matching_reply_keeps_original_response_deadline(self):
        t,p=await self.make();p.session.begin_turn();await p.commands();p.prepared=('new input',112.,'yes',p.revision)
        # Observe launch without running a supplier or fabricating a commit.
        gate=asyncio.Event()
        async def pending(*args):await gate.wait()
        with patch.object(p,'respond',pending):
            await p.handle(json.dumps(dict(v=2,type='stop',epoch=1,seq=0,intent='yes')))
            self.assertEqual(p.session.deadline,112.);self.assertIsNotNone(p.generation)
            p.generation.cancel();await asyncio.gather(p.generation,return_exceptions=True)

    async def test_runner_admission_failure_has_fixed_stage_and_no_exception_body(self):
        t,p=await self.make();p.closed=True
        with self.assertRaises(soak.AttemptFailure) as caught:await t.attempt('合成输入','normal')
        result=soak.failure_metadata(caught.exception,transport=t)
        self.assertEqual(result['stage'],'admission');self.assertEqual(result['reason'],'session_closed')
        self.assertTrue(result['peer_closed'])
        result=soak.failure_metadata(RuntimeError('PRIVATE_CANARY'))
        self.assertNotIn('PRIVATE_CANARY',json.dumps(result))
