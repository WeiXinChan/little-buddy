"""Real monotonic lease contrast; no fakeclock, lease/budget changes or cloud."""
import asyncio
from contextlib import asynccontextmanager
import json
import time
import unittest
from unittest.mock import patch
from backend.v2.companion import UnifiedProviders
from scripts import v2_multiturn_probe as probe
from tests.v2 import test_multiturn_probe as fixtures
from tests.v2.test_m05 import Model,plan

class Heartbeat(unittest.IsolatedAsyncioTestCase):
    async def test_real_elapsed_over_15s_missing_heartbeat_expires_periodic_delivery_survives(self):
        class Speech:
            def __init__(self):self.calls=0
            @asynccontextmanager
            async def synthesize(self,text,rate):
                self.calls+=1;index=self.calls
                async def frames():
                    yield b'\x01\x00'*4800 # actual reframe enables first ACK before 15s
                    if index==1:await asyncio.sleep(16.1)
                    yield b'\x01\x00'*2400
                yield frames()
        def providers():
            model=Model(plan());model.next_plan.update(mode='story',rules='轮流编故事',roles=['小猫'],anchors={})
            return UnifiedProviders(Speech(),model)
        old,new=providers(),providers();peers=[];trace=[]
        actual=probe.VoicePeer;heartbeat=probe.client_heartbeat
        class Peer(actual):
            def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);peers.append(self)
            async def handle(self,raw):
                event=json.loads(raw)
                trace.append((self.providers is new,event['type'],event['epoch'],event['seq'],time.monotonic(),self.session.expires))
                await super().handle(raw)
        async def contrast(client):
            if client.peer.providers is old:await asyncio.Future() # original harness: no heartbeat
            else:await heartbeat(client)
        start=time.monotonic()
        with patch.object(probe,'VoicePeer',Peer),patch.object(probe,'client_heartbeat',contrast):
            old_report,new_report=await asyncio.gather(probe.run_case(fixtures.CASE,old),probe.run_case(fixtures.CASE,new))
        elapsed=time.monotonic()-start
        self.assertGreaterEqual(elapsed,16)
        self.assertFalse(old_report['turns'][0]['checks']['delivery'])
        self.assertFalse(old_report['turns'][0]['checks']['played_context'])
        self.assertEqual(old_report['client_heartbeats'],0)
        self.assertTrue(all(all(t['checks'].values()) for t in new_report['turns']))
        self.assertEqual(len(new_report['turns']),3);self.assertGreaterEqual(new_report['client_heartbeats'],4)
        first=new_report['turns'][0]
        self.assertGreater(first['completed_ms'],15000);self.assertTrue(first['delivery_metadata']['game_committed'])
        pulses=[r for r in trace if r[0] and r[1]=='heartbeat']
        self.assertTrue(all(4.8<=b[4]-a[4]<6 for a,b in zip(pulses,pulses[1:])))
        self.assertEqual(len({r[5] for r in pulses}),1) # heartbeat did not extend child idle TTL
        commands=[r for r in trace if r[0]]
        self.assertEqual([r[3] for r in commands],list(range(len(commands))))
        self.assertTrue(all(r[2]==0 for r in commands))
        self.assertTrue(all(p.session.lease==15 and p.session.budget==15 for p in peers))
        self.assertTrue(old_report['cleanup']['confirmed'] and new_report['cleanup']['confirmed'])
        self.assertTrue(all(p.providers.probe_cleanup_handle is None for p in peers))
        print(json.dumps({'elapsed_ms':round(elapsed*1000),'without_heartbeat_delivery':False,'with_heartbeat_delivery':True,'heartbeats':new_report['client_heartbeats'],'lease':15,'budget':15,'cloud_calls':0}))

    async def test_client_sequence_serialized_and_epoch_change_cannot_be_borrowed(self):
        p=probe.VoicePeer(probe.Sink(),fixtures.Probe().providers(),probe.CompanionPolicy())
        state=probe.BatchState();client=probe.ProbeClient(p,state)
        await asyncio.gather(client.send('heartbeat'),client.send('heartbeat'))
        self.assertEqual(p.sequence,1);self.assertEqual(client.heartbeats,2)
        p.epoch+=1
        with self.assertRaises(probe.ProbeLimit):await client.send('heartbeat')
        self.assertEqual(p.sequence,1)
        state.open=False
        with self.assertRaises(probe.ProbeLimit):await client.send('heartbeat')

    async def test_heartbeat_task_failure_cancels_batch_and_closes_meter_gate(self):
        p=probe.VoicePeer(probe.Sink(),fixtures.Probe().providers(),probe.CompanionPolicy())
        state=probe.BatchState();client=probe.ProbeClient(p,state)
        p.epoch+=1
        await probe.client_heartbeat(client)
        self.assertTrue(client.failed);self.assertFalse(state.open)
        with self.assertRaises(probe.ProbeLimit):state.ensure()

    async def test_batch_closes_and_reaps_heartbeat_no_late_command(self):
        clients=[];tasks=[];real=probe.client_heartbeat
        async def captured(client):
            clients.append(client);tasks.append(asyncio.current_task());await real(client)
        with patch.object(probe,'client_heartbeat',captured):
            report=await probe.run_case(fixtures.CASE,fixtures.Probe().providers())
        self.assertTrue(report['cleanup']['confirmed']);self.assertFalse(report['client_heartbeat_failed'])
        self.assertEqual(len(tasks),1);self.assertTrue(tasks[0].done())
        self.assertIn(tasks[0],clients[0].state.tasks);self.assertFalse(clients[0].state.open)
        old=clients[0].sequence
        with self.assertRaises(probe.ProbeLimit):await clients[0].send('heartbeat')
        self.assertEqual(clients[0].sequence,old)
