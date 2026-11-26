"""Fixture reaping contracts: retain late exit handles, no production changes."""
import asyncio
from contextlib import asynccontextmanager
import inspect
import time
import unittest
from tests.v2 import test_image_descriptions as images

class Cleanup(unittest.IsolatedAsyncioTestCase):
    async def scenario(self,stubborn):
        h=images.Descriptions();release=asyncio.Event();entered=asyncio.Event();block=asyncio.Event()
        provider,*_=await h.make()
        @asynccontextmanager
        async def speech(text,rate):
            async def frames():
                yield b'\x01\x00'*2400;yield b'\x01\x00'*2400;await block.wait()
            try:yield frames()
            finally:
                entered.set()
                while not release.is_set():
                    try:await release.wait()
                    except asyncio.CancelledError:
                        if not stubborn:raise
        provider.speech.synthesize=speech
        peer,_=await h.run_wire(provider,full=False)
        return h,peer,release,entered,block
    async def finish(self,h,p,release,block):
        release.set();block.set()
        tasks=set(getattr(p,'_test_cleanup_tasks',()))|set(p.retired_tasks)
        if p.generation:tasks.add(p.generation)
        if p.visual_task:tasks.add(p.visual_task)
        if tasks:
            done,pending=await asyncio.wait(tasks,timeout=1)
            self.assertFalse(pending)
            for task in done:
                if not task.cancelled():task.exception() # explicit teardown observation
        for fn,args,kwargs in reversed(h._cleanups):
            if getattr(fn,'__name__','')=='cleanup':continue
            result=fn(*args,**kwargs)
            if inspect.isawaitable(result):await result

    async def test_new_exit_created_by_cancel_is_confirmed_without_duplicate_cancel(self):
        h,p,release,entered,block=await self.scenario(False)
        async def confirm():await entered.wait();release.set()
        confirmation=asyncio.create_task(confirm())
        try:
            await h.cleanup(p);await confirmation
            self.assertFalse(p._test_cleanup_pending);self.assertTrue(p._test_cleanup_resource_confirmed)
            self.assertGreater(len(p._test_cleanup_tasks),1)
            self.assertTrue(all(t.done() for t in p._test_cleanup_tasks))
        finally:release.set();await confirmation;await self.finish(h,p,release,block)

    async def test_stubborn_late_exit_fails_with_retained_handles_within_one_deadline(self):
        h,p,release,entered,block=await self.scenario(True);start=time.monotonic()
        try:
            with self.assertRaises(AssertionError):await h.cleanup(p)
            self.assertLess(time.monotonic()-start,2.3)
            self.assertTrue(p._test_cleanup_pending)
            self.assertTrue(p._test_cleanup_pending<=p._test_cleanup_tasks)
            self.assertTrue(p.closed)
        finally:await self.finish(h,p,release,block)

    async def test_new_retired_task_failure_is_explicit_not_gathered_as_success(self):
        h,p,release,entered,block=await self.scenario(False)
        class FixtureFailure(RuntimeError):pass
        async def failed():raise FixtureFailure('synthetic late task')
        original=p.track_retired;added=[]
        def track(task):
            original(task)
            if not added:
                extra=asyncio.create_task(failed());added.append(extra);original(extra)
        p.track_retired=track
        async def confirm():await entered.wait();release.set()
        confirmation=asyncio.create_task(confirm())
        try:
            with self.assertRaises(FixtureFailure):await h.cleanup(p)
            self.assertTrue(added);self.assertIn(added[0],p._test_observed_tasks)
            self.assertFalse(p._test_cleanup_pending)
        finally:release.set();await confirmation;await self.finish(h,p,release,block)

    async def test_completed_healthy_task_registered_at_final_yield_is_observed_and_confirmed(self):
        h=images.Descriptions();p=None;late=None
        try:
            provider,*_=await h.make();p,_=await h.run_wire(provider)
            async def completed():return 'synthetic closed'
            late=asyncio.create_task(completed());await asyncio.sleep(0)
            late.add_done_callback(p.track_retired)
            deadline=asyncio.get_running_loop().time()+2;p._test_cleanup_deadline=deadline
            await h.cleanup(p)
            self.assertIn(late,p._test_observed_tasks)
            self.assertIn(late,p._test_cleanup_tasks)
            self.assertTrue(p._test_cleanup_confirmed and p._test_cleanup_quiescent)
            self.assertEqual(p._test_cleanup_deadline,deadline)
        finally:
            if p:await self.finish(h,p,asyncio.Event(),asyncio.Event())
