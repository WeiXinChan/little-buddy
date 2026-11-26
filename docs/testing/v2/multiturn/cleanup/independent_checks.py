import sys,asyncio,unittest,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent/'source'))
from scripts import v2_multiturn_probe as probe
from tests.v2.test_multiturn_probe import CASE,Probe
from tests.v2.test_m05 import Model,plan
from backend.v2.companion import UnifiedProviders
class Independent(unittest.IsolatedAsyncioTestCase):
 async def test_outer_timeout_cleanup_of_stubborn_actual_provider_exit_is_bounded(self):
  entered=asyncio.Event();release=asyncio.Event();exits=[];captured=[]
  class Manager:
   async def __aenter__(self):
    async def frames():yield b'\x01\x00'*320
    return frames()
   async def __aexit__(self,*args):
    exits.append(asyncio.current_task());entered.set()
    while not release.is_set():
     try:await release.wait()
     except asyncio.CancelledError:pass
  class Speech:
   def synthesize(self,*args):return Manager()
  model=Model(plan());model.next_plan.update(mode='story',rules='轮流编故事',roles=['小猫'],anchors={})
  providers=UnifiedProviders(Speech(),model)
  real=probe.VoicePeer
  def peer(*args,**kwargs):p=real(*args,**kwargs);captured.append(p);return p
  original_timeout=asyncio.timeout
  def timeout(seconds):return original_timeout(.04 if seconds==45 else seconds)
  task=None;observed=None
  try:
   with patch.object(probe,'VoicePeer',peer),patch.object(probe.asyncio,'timeout',timeout):
    task=asyncio.create_task(probe.run_case(CASE,providers))
    await asyncio.wait_for(entered.wait(),1)
    done,_=await asyncio.wait({task},timeout=.8)
    observed={'finished':bool(done),'retired_tasks':len(captured[0].retired_tasks),'generation_done':captured[0].generation.done(),'provider_wrappers_restored':providers.model is model}
    print('STUBBORN_CLEANUP',json.dumps(observed))
  finally:
   release.set()
   if task is not None:await asyncio.wait_for(task,2)
   if exits:await asyncio.gather(*exits,return_exceptions=True)
  self.assertTrue(observed['finished'],'outer timeout expired but finally waits unboundedly on retired provider exit')
 async def test_rejected_async_observer_task_does_not_remain_running(self):
  release=asyncio.Event();tasks=[];ran=[]
  async def body():ran.append(True);await release.wait()
  def observer(*args):t=asyncio.create_task(body());tasks.append(t);return t
  p=Probe().providers()
  try:
   report=await probe.run_case(CASE,p,observer=observer)
   await asyncio.sleep(0)
   print('ASYNC_OBSERVER',json.dumps({'stopped':report['turns'][-1].get('failure'),'returned_task_done':tasks[0].done(),'body_ran':bool(ran)}))
   self.assertTrue(tasks[0].done(),'rejected awaitable observer Task remains live outside cleanup')
  finally:
   release.set()
   for t in tasks:t.cancel()
   await asyncio.gather(*tasks,return_exceptions=True)
if __name__=='__main__':unittest.main(defaultTest='Independent',verbosity=2)
