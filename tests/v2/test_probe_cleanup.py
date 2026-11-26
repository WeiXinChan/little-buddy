"""Finite cleanup observation with explicit release of every stubborn fixture."""
import asyncio
import unittest
from unittest.mock import patch
from scripts import v2_multiturn_probe as probe
from tests.v2 import test_multiturn_probe as fixtures
CASE=fixtures.CASE

class Cleanup(unittest.IsolatedAsyncioTestCase):
    async def release_all(self,p,release,task=None):
        release.set()
        if task:
            try:await task
            except asyncio.CancelledError:pass
        handle=p.probe_cleanup_handle
        if handle:
            for _ in range(5):
                pending=handle.pending()
                if not pending:break
                await asyncio.gather(*pending,return_exceptions=True)
                await asyncio.sleep(0)
            self.assertEqual(handle.pending(),())

    async def test_normal_cleanup_restores_provider_and_allows_next_explicit_case(self):
        p=fixtures.Probe().providers();model,speech=p.model,p.speech
        for _ in range(2):
            report=await probe.run_case(CASE,p)
            self.assertEqual(report['cleanup'],{'confirmed':True,'pending_tasks':0,'provider_reusable':True})
            self.assertTrue(report['usage_final']);self.assertIsNone(p.probe_cleanup_handle)
            self.assertIs(p.model,model);self.assertIs(p.speech,speech)

    async def test_rejected_future_cancelled_and_normal_wrappers_restored(self):
        p=fixtures.Probe().providers();model=p.model;future=asyncio.get_running_loop().create_future()
        report=await probe.run_case(CASE,p,observer=lambda *args:future)
        self.assertTrue(future.cancelled());self.assertIs(p.model,model)
        self.assertEqual(report['turns'][-1]['failure'],'ProbeLimit')
        self.assertTrue(report['cleanup']['confirmed'])

    async def test_already_running_stubborn_observer_is_retained_and_cannot_reuse_provider(self):
        entered=asyncio.Event();release=asyncio.Event();side_effects=[]
        async def stubborn():
            entered.set()
            while not release.is_set():
                try:await release.wait()
                except asyncio.CancelledError:pass
            side_effects.append('explicit_fixture_release')
        observer_task=asyncio.create_task(stubborn());await entered.wait()
        p=fixtures.Probe().providers();model=p.model
        try:
            report=await probe.run_case(CASE,p,observer=lambda *args:observer_task)
            self.assertFalse(report['cleanup']['confirmed']);self.assertFalse(report['usage_final'])
            self.assertEqual(report['turns'][-1]['failure'],'ProviderQuarantined')
            self.assertIn(observer_task,p.probe_cleanup_handle.pending())
            self.assertIsNot(p.model,model);self.assertEqual(side_effects,[])
            with self.assertRaises(probe.ProbeLimit):await probe.run_case(CASE,p)
            with self.assertRaises(probe.ProbeLimit):await p.model.complete('later',{},schema={})
            with self.assertRaises(probe.ProbeLimit):p.speech.synthesize('later',24000)
        finally:await self.release_all(p,release)
        self.assertTrue(p.probe_cleanup_handle.quarantined) # completion is not automatic reauthorization
        with self.assertRaises(probe.ProbeLimit):await probe.run_case(CASE,p)

    async def test_outer_budget_does_not_wait_for_model_cancellation_ack(self):
        p=fixtures.Probe().providers();model=p.model;entered=asyncio.Event();release=asyncio.Event()
        original=model.complete
        async def stubborn(*args,**kwargs):
            entered.set()
            while not release.is_set():
                try:await release.wait()
                except asyncio.CancelledError:pass
            return await original(*args,**kwargs)
        model.complete=stubborn
        original_timeout=asyncio.timeout
        def timeout(value):return original_timeout(.03 if value==45 else value)
        task=None
        try:
            with patch.object(probe.asyncio,'timeout',timeout):
                task=asyncio.create_task(probe.run_case(CASE,p));await entered.wait()
                done,_=await asyncio.wait({task},timeout=.7)
                self.assertTrue(done)
                report=task.result();self.assertFalse(report['cleanup']['confirmed'])
                self.assertFalse(p.probe_cleanup_handle.open)
                self.assertIsNot(p.model,model)
        finally:await self.release_all(p,release,task)
        self.assertEqual(len(model.requests),1) # in-flight fixture result only; no retry/new stage

    async def test_repeated_caller_cancellation_preserves_unconfirmed_handle(self):
        p=fixtures.Probe().providers();entered=asyncio.Event();release=asyncio.Event()
        async def stubborn(*args,**kwargs):
            entered.set()
            while not release.is_set():
                try:await release.wait()
                except asyncio.CancelledError:pass
            return '{}'
        p.model.complete=stubborn;task=asyncio.create_task(probe.run_case(CASE,p))
        try:
            await entered.wait();task.cancel();await asyncio.sleep(.01);task.cancel()
            done,_=await asyncio.wait({task},timeout=.5)
            self.assertTrue(done);self.assertTrue(task.cancelled())
            self.assertTrue(p.probe_cleanup_handle.quarantined)
            self.assertTrue(p.probe_cleanup_handle.pending())
            with self.assertRaises(probe.ProbeLimit):await probe.run_case(CASE,p)
        finally:await self.release_all(p,release,task)

    async def test_cooperative_caller_cancel_confirms_exit_and_restores_provider(self):
        p=fixtures.Probe().providers();model=p.model;entered=asyncio.Event()
        async def cooperative(*args,**kwargs):entered.set();await asyncio.Future()
        model.complete=cooperative;task=asyncio.create_task(probe.run_case(CASE,p))
        await entered.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertIs(p.model,model);self.assertIsNone(p.probe_cleanup_handle)
