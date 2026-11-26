"""Short real-clock falsifiers; never A36/60-minute acceptance."""
import asyncio
import json
import time
import unittest
from unittest.mock import patch
from scripts import v2_soak as soak
from backend.v2.companion import UnifiedProviders
from scripts.v2_multiturn_probe import ProbeLimit

class Soak(unittest.IsolatedAsyncioTestCase):
    def limits(self,**kwargs):
        fields=dict(duration=.22,interval=.03,sample_interval=.02,attempt_timeout=.12,max_attempts=3)
        fields.update(kwargs);return soak.Limits(**fields)

    async def test_real_elapsed_schedule_waits_not_rapid_count_and_never_claims_hour(self):
        start=time.monotonic();r=await soak.run_soak(self.limits(max_attempts=2))
        self.assertGreaterEqual(time.monotonic()-start,.22)
        self.assertEqual(r['attempted'],2);self.assertEqual(r['delivered'],2)
        self.assertGreaterEqual(r['attempts'][1]['started'],.025)
        self.assertFalse(r['wall_60_minutes_observed'] or r['full_acceptance'] or r['p14_verified'])
        self.assertTrue(r['cleanup']['confirmed']);self.assertGreater(len(r['resource_samples']),2)
        self.assertIsNone(r['allowance']['bill_cny']);self.assertIsNone(r['usage_delta']['prompt_tokens'])

    async def test_mixed_actual_protocol_interrupt_and_injected_network_are_distinct(self):
        r=await soak.run_soak(self.limits(duration=1.3,interval=.18,attempt_timeout=.5,max_attempts=6))
        self.assertEqual([row['injected'] for row in r['attempts']],['normal','normal','interrupt','delay','drop','normal'])
        self.assertEqual(r['attempted'],6);self.assertEqual(r['delivered'],4);self.assertEqual(r['interrupted_attempts'],2)
        self.assertEqual(r['delivery_rate_all_attempts'],4/6)
        self.assertTrue(all(row['observed']['interrupted'] for row in r['attempts'] if row['injected'] in {'interrupt','drop'}))
        self.assertTrue(all(row['observed']['acoustic_reply_ms'] is None for row in r['attempts']))
        self.assertEqual(r['cleanup']['pending_tasks'],0)
        raw=json.dumps(r,ensure_ascii=False)
        for _,text,_ in soak.SCENARIOS:self.assertNotIn(text,raw)
        self.assertNotIn('小猫慢慢出发',raw)
        self.assertIsNone(r['resource_samples'][0]['device_rss_bytes'])

    async def test_external_cloud_and_device_are_off_by_default_before_io(self):
        providers=UnifiedProviders(soak.OfflineSpeech(),soak.OfflineModel())
        with self.assertRaisesRegex(ProbeLimit,'cloud_disabled'):await soak.run_soak(self.limits(),providers=providers)
        with self.assertRaisesRegex(ProbeLimit,'device_driver_not_integrated'):await soak.run_soak(self.limits(),allow_device=True)
        with self.assertRaisesRegex(ProbeLimit,'cloud_budget_required'):await soak.run_soak(self.limits(),providers=providers,allow_cloud=True)
        with self.assertRaisesRegex(ProbeLimit,'cloud_budget_not_reviewed'):await soak.run_soak(self.limits(),providers=providers,allow_cloud=True,cloud_budget=soak.CloudBudget(10,1,1))
        self.assertFalse(hasattr(providers,'probe_cleanup_handle'))
        for limits in (self.limits(duration=3601),self.limits(model_calls=0),self.limits(sample_interval=.00001)):
            with self.assertRaises(ValueError):await soak.run_soak(limits)

    async def test_all_failed_attempts_are_counted_and_global_allowance_not_reset(self):
        r=await soak.run_soak(self.limits(model_calls=1,allowance_units=2))
        self.assertEqual(r['attempted'],1);self.assertEqual(r['failures'],1);self.assertEqual(r['delivered'],0)
        self.assertEqual(r['allowance']['model_calls'],1);self.assertEqual(r['allowance']['tts_calls'],0)
        self.assertEqual(r['delivery_rate_all_attempts'],0)
        self.assertTrue(r['cleanup']['confirmed'])
        a=soak.Allowance(self.limits(model_calls=2,tts_calls=1,tts_characters=3,allowance_units=3))
        a.take('model');a.take('tts',3);a.take('model')
        with self.assertRaises(ProbeLimit):a.take('model')
        self.assertEqual(a.report()['reserved_units'],3)

    async def test_stop_event_returns_failure_denominator_and_restores_confirmed_provider(self):
        entered=asyncio.Event()
        class Slow(soak.OfflineModel):
            async def complete(self,*args,**kwargs):entered.set();await asyncio.Future()
        providers=UnifiedProviders(soak.OfflineSpeech(),Slow());original=providers.model;stop=asyncio.Event()
        task=asyncio.create_task(soak.run_soak(self.limits(duration=1),providers=providers,allow_cloud=True,stop=stop,cloud_budget=soak.CloudBudget(960,1,1,True)))
        await entered.wait();stop.set();r=await task
        self.assertEqual(r['attempted'],1);self.assertEqual(r['failures'],1)
        self.assertEqual(r['attempts'][0]['status'],'cancelled')
        self.assertTrue(r['cleanup']['confirmed']);self.assertIs(providers.model,original)
        self.assertIsNone(providers.probe_cleanup_handle)

    async def test_stubborn_provider_bounded_cleanup_closed_meter_and_nonreuse(self):
        entered=asyncio.Event();release=asyncio.Event()
        class Stubborn(soak.OfflineModel):
            async def complete(self,*args,**kwargs):
                entered.set()
                while not release.is_set():
                    try:await release.wait()
                    except asyncio.CancelledError:pass
                return '{"facts":[]}'
        providers=UnifiedProviders(soak.OfflineSpeech(),Stubborn());original=providers.model
        stop=asyncio.Event();task=asyncio.create_task(soak.run_soak(self.limits(duration=1),providers=providers,allow_cloud=True,stop=stop,cloud_budget=soak.CloudBudget(960,1,1,True)))
        await entered.wait();start=time.monotonic();stop.set()
        try:
            r=await task
            self.assertLess(time.monotonic()-start,1.5)
            self.assertFalse(r['cleanup']['confirmed'] or r['cleanup']['provider_reusable'])
            self.assertGreater(r['cleanup']['pending_tasks'],0);self.assertIsNot(providers.model,original)
            with self.assertRaises(ProbeLimit):await providers.model.complete('no further IO',{})
            with self.assertRaises(ProbeLimit):await soak.run_soak(self.limits(),providers=providers,allow_cloud=True,cloud_budget=soak.CloudBudget(960,1,1,True))
        finally:
            release.set()
            await asyncio.wait(providers.probe_cleanup_handle.pending(),timeout=1)

    async def test_timeout_and_provider_quota_failure_stop_without_retry(self):
        from backend.v2.voice import VoiceFault
        class Slow(soak.OfflineModel):
            async def complete(self,*args,**kwargs):await asyncio.Future()
        class Quota(soak.OfflineModel):
            async def complete(self,*args,**kwargs):raise VoiceFault('quota')
        for model in (Slow(),Quota()):
            with self.subTest(provider=type(model).__name__):
                providers=UnifiedProviders(soak.OfflineSpeech(),model)
                r=await soak.run_soak(self.limits(),providers=providers,allow_cloud=True,cloud_budget=soak.CloudBudget(960,1,1,True))
                self.assertEqual(r['attempted'],1);self.assertEqual(r['failures'],1)
                self.assertTrue(r['cleanup']['confirmed']);self.assertEqual(r['delivered'],0)
                self.assertLessEqual(r['allowance']['model_calls'],2) # concurrent PLAN/FACTS, no new attempt

    async def test_caller_cancellation_and_resource_failures_are_observable(self):
        task=asyncio.create_task(soak.run_soak(self.limits(duration=1,interval=.5)))
        await asyncio.sleep(.03);task.cancel();r=await task
        self.assertTrue(r['caller_cancelled']);self.assertEqual(r['stop_reason'],'caller_cancelled')
        self.assertTrue(r['cleanup']['confirmed'])
        with patch.object(soak.Path,'read_text',side_effect=OSError('SECRET')):
            sample=soak.resources()
        self.assertIsNone(sample['backend_rss_bytes']);self.assertNotIn('SECRET',json.dumps(sample))
