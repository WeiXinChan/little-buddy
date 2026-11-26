import sys,unittest,asyncio,inspect
from pathlib import Path
from contextlib import asynccontextmanager
sys.path.insert(0,str(Path(__file__).resolve().parent/'source'))
from tests.v2.test_image_descriptions import Descriptions
class Independent(unittest.IsolatedAsyncioTestCase):
 async def test_cleanup_must_include_new_retired_exit_tasks_created_during_cancel(self):
  h=Descriptions();release=asyncio.Event();stream_block=asyncio.Event();peer=None;pending=[];error=None
  provider,*_=await h.make()
  @asynccontextmanager
  async def speech(text,rate):
   async def frames():
    yield b'\x01\x00'*2400;yield b'\x01\x00'*2400
    await stream_block.wait()
   try:yield frames()
   finally:
    while not release.is_set():
     try:await release.wait()
     except asyncio.CancelledError:pass
  provider.speech.synthesize=speech
  try:
   peer,_=await h.run_wire(provider,full=False)
   try:await h.cleanup(peer)
   except Exception as e:error=type(e).__name__
   pending=[x for x in peer.retired_tasks if not x.done()]
   print('CLEANUP_NEW_RETIRED',{'cleanup_error':error,'pending_after_cleanup':len(pending)})
   self.assertTrue(error is not None or not pending,'cleanup must not return success with unconfirmed new retired tasks; explicit failure is valid when a stubborn task cannot be stopped')
  finally:
   release.set();stream_block.set()
   tasks=set(pending)
   if peer:
    tasks|=set(peer.retired_tasks)
    if peer.generation:tasks.add(peer.generation)
    if peer.visual_task:tasks.add(peer.visual_task)
   for t in tasks:
    if not t.done():t.cancel()
   if tasks:await asyncio.gather(*tasks,return_exceptions=True)
   for function,args,kwargs in reversed(h._cleanups):
    if getattr(function,'__name__','')=='cleanup':continue
    value=function(*args,**kwargs)
    if inspect.isawaitable(value):await value
if __name__=='__main__':unittest.main(defaultTest='Independent',verbosity=2)
