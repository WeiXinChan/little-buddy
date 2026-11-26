import asyncio,sys,unittest,inspect
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'source'))
from tests.v2.test_image_descriptions import Descriptions
class Adjacent(unittest.IsolatedAsyncioTestCase):
 async def test_done_failure_registered_at_quiescent_yield_must_be_observed(self):
  h=Descriptions();peer=None;late=None
  class FixtureFailure(RuntimeError):pass
  async def failed():raise FixtureFailure('synthetic completed exit error')
  try:
   provider,*_=await h.make();peer,_=await h.run_wire(provider)
   late=asyncio.create_task(failed());await asyncio.sleep(0);self.assertTrue(late.done())
   # Retire a completed task on the exact quiescence yield used for final collection.
   late.add_done_callback(peer.track_retired)
   error=None
   try:await h.cleanup(peer)
   except FixtureFailure:error='FixtureFailure'
   print('QUIESCENT_RETIRED_FAILURE',{'raised':error,'late_in_retained':late in peer._test_cleanup_tasks,'late_observed':late in peer._test_observed_tasks,'cleanup_confirmed':peer._test_cleanup_confirmed})
   self.assertEqual(error,'FixtureFailure','newly collected done failure must be observed before cleanup confirms success')
  finally:
   tasks=set()
   if peer:
    tasks|=set(getattr(peer,'_test_wire_tasks',()))|set(getattr(peer,'_test_cleanup_tasks',()))|set(peer.retired_tasks)
    if peer.generation:tasks.add(peer.generation)
    if peer.visual_task:tasks.add(peer.visual_task)
   if late:tasks.add(late)
   for task in tasks:
    if not task.done():task.cancel()
   if tasks:await asyncio.gather(*tasks,return_exceptions=True)
   for fn,args,kwargs in reversed(h._cleanups):
    if getattr(fn,'__name__','')=='cleanup':continue
    result=fn(*args,**kwargs)
    if inspect.isawaitable(result):await result
 async def test_prior_and_new_quarantine_do_not_hide_errors_or_become_reusable(self):
  from tests.v2.test_image_descriptions import VoicePeer,Socket,CompanionPolicy
  for mode in ('prior','new','prior_with_error'):
   h=Descriptions();task=None
   class FixtureFailure(RuntimeError):pass
   async def failed():raise FixtureFailure('synthetic quarantined error')
   try:
    provider,*_=await h.make();peer=VoicePeer(Socket(),provider,CompanionPolicy())
    peer.quarantined=mode!='new'
    if mode=='new':
     asyncio.get_running_loop().call_soon(setattr,peer,'quarantined',True)
     with self.assertRaises(AssertionError):await h.cleanup(peer)
    elif mode=='prior_with_error':
     task=asyncio.create_task(failed());await asyncio.sleep(0);peer._test_wire_tasks={task}
     with self.assertRaises(FixtureFailure):await h.cleanup(peer)
    else:await h.cleanup(peer)
    self.assertTrue(peer.quarantined);self.assertTrue(peer.closed)
    self.assertFalse(peer._test_cleanup_confirmed or peer._test_cleanup_resource_confirmed)
   finally:
    if task:await asyncio.gather(task,return_exceptions=True)
    for fn,args,kwargs in reversed(h._cleanups):
     value=fn(*args,**kwargs)
     if inspect.isawaitable(value):await value
if __name__=='__main__':unittest.main(defaultTest='Adjacent',verbosity=2)
