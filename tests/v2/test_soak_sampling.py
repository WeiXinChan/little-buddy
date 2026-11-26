"""Lifecycle sample falsifiers, no invented active/retired counts."""
import asyncio
import json
import unittest
from unittest.mock import patch
from scripts import v2_soak as soak
from backend.v2.companion import UnifiedProviders

class Sampling(unittest.IsolatedAsyncioTestCase):
    def limits(self):return soak.Limits(duration=.08,interval=.08,sample_interval=.08,attempt_timeout=.06,max_attempts=1)

    async def test_zero_await_model_operation_is_captured_at_real_registry_mutation(self):
        transports=[];actual=soak.BackendTransport
        class Transport(actual):
            def __init__(self,*args):super().__init__(*args);transports.append(self)
        with patch.object(soak,'BackendTransport',Transport):r=await soak.run_soak(self.limits())
        active=[s for s in r['resource_samples'] if s['phase']=='operation_started']
        self.assertTrue(active);self.assertGreater(active[0]['active_operations'],0)
        self.assertGreater(r['resource_trends']['active_operations']['maximum'],0)
        self.assertEqual(len(transports[0].peer.generation_scopes),0)
        self.assertEqual(r['resource_trends']['active_operations']['maximum_kind'],'observed_sample_maximum')
        self.assertFalse(r['sampling']['continuous_peaks_known'])
        self.assertTrue(r['resource_collection_valid'])

    async def test_real_peak_is_retained_after_small_ring_evicts_active_rows(self):
        actual=soak.ResourceCollector
        class Small(actual):
            def __init__(self,*args):super().__init__(*args,capacity=2)
        with patch.object(soak,'ResourceCollector',Small):r=await soak.run_soak(self.limits())
        self.assertEqual(len(r['resource_samples']),2);self.assertGreater(r['sampling']['evicted'],0)
        self.assertTrue(all(s['active_operations']==0 for s in r['resource_samples']))
        self.assertGreater(r['resource_trends']['active_operations']['maximum'],0)
        self.assertEqual(r['resource_trends']['active_operations']['last'],0)

    async def test_cancel_cleanup_and_real_retired_task_changes_are_observed(self):
        entered=asyncio.Event();release=asyncio.Event();stop=asyncio.Event()
        class Stubborn(soak.OfflineModel):
            async def complete(self,*args,**kwargs):
                entered.set()
                while not release.is_set():
                    try:await release.wait()
                    except asyncio.CancelledError:pass
                return '{"facts":[]}'
        p=UnifiedProviders(soak.OfflineSpeech(),Stubborn())
        task=asyncio.create_task(soak.run_soak(soak.Limits(duration=1,interval=1,sample_interval=.05,attempt_timeout=.5,max_attempts=1),providers=p,allow_cloud=True,cloud_budget=soak.CloudBudget(960,1,1,True),stop=stop))
        await entered.wait();stop.set()
        try:
            r=await task;phases={s['phase'] for s in r['resource_samples']}
            self.assertTrue({'before_attempt_cancel','after_attempt_cancel','before_transport_cleanup','after_transport_cleanup','after_owner_cleanup','final'}<=phases)
            self.assertGreater(r['resource_trends']['retired_pending']['maximum'],0)
            self.assertFalse(r['cleanup']['confirmed'] or r['resource_collection_valid'] or r['p14_verified'])
            self.assertGreater(r['cleanup']['pending_tasks'],0)
        finally:
            release.set();await asyncio.wait(p.probe_cleanup_handle.pending(),timeout=1)

    async def test_sample_errors_and_unknown_resources_are_not_valid_collection_or_raw_logs(self):
        with patch.object(soak,'resources',side_effect=RuntimeError('PRIVATE_CANARY')):
            r=await soak.run_soak(self.limits())
        self.assertGreater(r['sampling']['errors'],0)
        self.assertFalse(r['sampling']['valid'] or r['resource_collection_valid'])
        self.assertNotIn('PRIVATE_CANARY',json.dumps(r));self.assertIsNone(r['resource_trends']['active_operations']['maximum'])
        with patch.object(soak.Path,'read_text',side_effect=OSError('PRIVATE')):
            r=await soak.run_soak(self.limits())
        self.assertIn('backend_rss_bytes',r['sampling']['missing_metrics'])
        self.assertFalse(r['resource_collection_valid'] or r['p14_verified'])

    async def test_phase_event_does_not_synthesize_nonexistent_operation(self):
        p=UnifiedProviders(soak.OfflineSpeech(),soak.OfflineModel());transport=soak.BackendTransport(p)
        import time
        collector=soak.ResourceCollector(transport,soak.Allowance(self.limits()),time.monotonic())
        collector.record('operation_started');collector.record('PRIVATE_CANARY')
        self.assertEqual(collector.summary()['active_operations']['maximum'],0)
        self.assertEqual(collector.rows[-1]['phase'],'unknown')
        self.assertNotIn('PRIVATE_CANARY',json.dumps(list(collector.rows)))
