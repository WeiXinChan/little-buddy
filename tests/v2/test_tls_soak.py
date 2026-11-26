"""Real local TLS/relay fixtures, no external DNS/cloud/device."""
import asyncio
import json
import time
import unittest
from unittest.mock import patch
from scripts import v2_tls_soak as net
from scripts.v2_soak import Limits

class TlsSoak(unittest.IsolatedAsyncioTestCase):
    def limits(self,**kw):return Limits(**dict(dict(duration=12,interval=.01,sample_interval=.02,attempt_timeout=2,max_attempts=14),**kw))

    async def test_six_fault_triggers_and_new_session_recovery_have_global_accounting(self):
        report=await net.run_tls_soak(self.limits(),seed=31)
        self.assertEqual(report['attempted'],14);self.assertEqual(report['failures'],0);self.assertTrue(report['resource_collection_valid'])
        self.assertEqual(report['injected_fault_attempts'],4);self.assertEqual(report['interrupted_attempts'],1);self.assertEqual(report['delivered'],9)
        self.assertTrue(report['cleanup']['confirmed']);self.assertEqual(report['cleanup']['pending_tasks'],0)
        self.assertEqual(report['connections_attempted'],14);self.assertEqual(len(report['connection_ledger']),14);self.assertEqual(report['peers_constructed'],14)
        rows=report['attempts'];self.assertEqual(set(r['fault'] for r in rows),set(net.MATRIX))
        for row in rows:
            if row['fault'] in {'pause_resume','half_open'}:self.assertTrue(row['pause_observed'])
            if row['fault'] in {'normal_close','pause_resume'}:self.assertTrue(row['close_handshake_confirmed'])
            self.assertTrue(row['cleanup_confirmed']);self.assertTrue(row['session_cleared']);self.assertTrue(row['new_session'])
            self.assertGreater(row['relay_bytes']['up'],0);self.assertGreater(row['relay_bytes']['down'],0)
            self.assertLessEqual(row['relay_buffer_observed_max'],16384)
            if row['status'] in {'fault_injected','interrupted'}:self.assertEqual(row['heard_before_close'],0)
            if row['status']=='fault_injected':self.assertTrue(row['rst_applied'])
        self.assertTrue(all(row['old_ack_checked'] for row in rows if row['status']=='delivered' and row['index']>0))
        trends=report['resource_trends']
        self.assertGreater(trends['active_operations']['maximum'],0)
        self.assertGreater(trends['retired_pending']['maximum'],0)
        self.assertEqual(trends['active_operations']['last'],0)
        self.assertEqual(trends['tts_active']['last'],0)
        self.assertGreater(report['allowance']['model_calls'],12)
        self.assertEqual(sum(report['model_stage_calls'].values()),report['allowance']['model_calls'])
        self.assertFalse(report['p14_verified']);self.assertFalse(report['full_acceptance']);self.assertIsNone(report.cleanup_handle)
        encoded=json.dumps(report,ensure_ascii=False)
        for forbidden in ('SyntheticOnly','你出动物','identity','pcm','BEGIN PRIVATE','Bearer'):self.assertNotIn(forbidden,encoded)

    async def test_unconfirmed_exit_stops_and_preserves_real_pending_handles_no_reconnect(self):
        t=net.LoopbackTlsTransport(self.limits());await t.start()
        t.speech.stubborn=True;t.speech.release.clear()
        try:
            row=await t.attempt(net.TEXTS[0],'partial_rst')
            self.assertFalse(row['cleanup_confirmed']);self.assertTrue(t.quarantined)
            self.assertGreater(row['pending_after_cleanup'],0)
            self.assertGreater(t.speech.tts_active,0)
            with self.assertRaisesRegex(RuntimeError,'isolated'):await t.attempt(net.TEXTS[1],'normal_close')
            self.assertEqual(len(t.connections),1)
            cleanup=await t.close();self.assertFalse(cleanup['confirmed']);self.assertTrue(cleanup['isolated'])
        finally:
            t.speech.release.set()
            good,pending,errors=await net.drain(t.handles,time.monotonic()+2)
            self.assertFalse(pending);self.assertEqual(t.speech.tts_active,0)

    async def test_plan_late_result_cannot_publish_after_rst(self):
        t=net.LoopbackTlsTransport(self.limits());original=t.model.complete;late=asyncio.Event()
        async def late_plan(instruction,data,*,schema=None):
            if 'mode' in (schema or {}).get('properties',{}):
                t.model.plan_entered.set()
                try:await t.model.plan_gate.wait()
                except asyncio.CancelledError:late.set() # deliberately returns after revocation
                return await net.OfflineModel.complete(t.model,instruction,data,schema=schema)
            return await original(instruction,data,schema=schema)
        t.model.complete=late_plan
        await t.start()
        try:
            first=await t.attempt(net.TEXTS[0],'plan_rst');self.assertTrue(late.is_set())
            self.assertEqual(first['frames'],0);self.assertTrue(first['cleanup_confirmed'])
            self.assertEqual(first['old_heard_count'],0)
            t.model.complete=original
            fresh=await t.attempt(net.TEXTS[1],'normal_close')
            self.assertEqual(fresh['status'],'delivered');self.assertTrue(fresh['new_session'])
            self.assertTrue(t.peers[0].closed);self.assertFalse(t.peers[0].session.pending)
        finally:self.assertTrue((await t.close())['confirmed'])

    async def test_attempt_deadline_stops_failure_in_denominator_and_cleans(self):
        report=await net.run_tls_soak(self.limits(attempt_timeout=.0001,max_attempts=2))
        self.assertEqual(report['attempted'],1);self.assertEqual(report['failures'],1)
        self.assertEqual(report['stop_reason'],'attempt_timeout');self.assertEqual(report['connections_attempted'],1)
        self.assertFalse(report['p14_verified'])
        if report.cleanup_handle:
            transport=report.cleanup_handle
            self.assertTrue(transport.closed);self.assertFalse(transport.allowance.open)
            await net.drain(transport.handles,time.monotonic()+2)

    async def test_global_allowance_is_not_reset_by_reconnect_and_attempt_cap_does_not_idle(self):
        start=time.monotonic()
        r=await net.run_tls_soak(self.limits(model_calls=6))
        self.assertLessEqual(r['allowance']['model_calls'],6)
        self.assertLess(r['attempted'],14);self.assertGreaterEqual(r['failures'],1)
        self.assertLess(time.monotonic()-start,5)
        r=await net.run_tls_soak(self.limits(max_attempts=1))
        self.assertEqual(r['stop_reason'],'attempt_cap');self.assertLess(r['elapsed_seconds'],5)

    async def test_cancelled_schedule_cleans_heartbeat_relay_and_server(self):
        stop=asyncio.Event()
        async def stopping():await asyncio.sleep(.5);stop.set()
        trigger=asyncio.create_task(stopping())
        r=await net.run_tls_soak(self.limits(interval=1),stop=stop);await trigger
        self.assertEqual(r['stop_reason'],'cancelled');self.assertTrue(r['cleanup']['confirmed'])
        self.assertEqual(r['cleanup']['pending_tasks'],0)

    async def test_dynamic_final_drain_observes_done_error_and_retains_stubborn(self):
        handles=set()
        async def bad():raise ValueError('not serialized')
        task=asyncio.create_task(bad());await asyncio.sleep(0)
        task.add_done_callback(handles.add)
        ok,pending,errors=await net.drain(lambda:handles,time.monotonic()+.1)
        self.assertFalse(ok);self.assertEqual(errors,1);self.assertFalse(pending)
        release=asyncio.Event()
        async def stubborn():
            while not release.is_set():
                try:await release.wait()
                except asyncio.CancelledError:continue
        task=asyncio.create_task(stubborn());await asyncio.sleep(0);task.cancel();handles={task}
        ok,pending,errors=await net.drain(lambda:handles,time.monotonic()+.02)
        self.assertFalse(ok);self.assertEqual(pending,{task})
        release.set();await task
