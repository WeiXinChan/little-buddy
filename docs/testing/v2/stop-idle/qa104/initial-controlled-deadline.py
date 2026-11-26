import asyncio,sys,unittest,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent/'source'))
from tests.v2.test_stop_idle import StopIdle
from backend.v2.voice import WireError
class Independent(unittest.IsolatedAsyncioTestCase):
 async def make(self,run=False):return await StopIdle.make(self,run)
 async def old_generation(self,p):
  entered=asyncio.Event();release=asyncio.Event()
  async def old():
   try:await asyncio.Future()
   except asyncio.CancelledError:entered.set();await release.wait()
  p.generation=asyncio.create_task(old());await asyncio.sleep(0)
  return entered,release
 async def test_new_prepared_deadline_is_not_hidden_by_old_stop_token(self):
  t,p=await self.make();p.session.begin_turn();await p.commands();entered,release=await self.old_generation(p)
  stop=asyncio.create_task(p.handle(json.dumps(dict(v=2,type='stop',epoch=1,seq=0,intent='old-stop'))));await entered.wait()
  p.prepared=('new expression',119.,'new-intent',p.revision);p.session.deadline=119.;self.now[0]=119.01
  monitor=asyncio.create_task(p.monitor())
  try:
   await asyncio.sleep(.13)
   print('NEW_PREPARED_MONITOR',{'monitor_done':monitor.done(),'response_expired':p.session.response_expired,'old_stop_pending':not stop.done(),'new_prepared_deadline':119})
   self.assertTrue(p.session.response_expired or monitor.done(),'replacement prepared/new reply deadline must be polled, not suppressed by old cancellation token')
  finally:
   release.set();await stop;monitor.cancel();await asyncio.gather(monitor,return_exceptions=True)
 async def test_commands_exception_does_not_clear_deadline_or_leave_settling_token(self):
  t,p=await self.make();p.session.begin_turn();deadline=p.session.deadline;lease=(p.session.expires,p.session.heartbeat_deadline)
  async def fail():raise WireError('PRIVATE_COMMANDS')
  with patch.object(p,'commands',fail):
   with self.assertRaises(WireError):await p.handle(json.dumps(dict(v=2,type='stop',epoch=1,seq=0,intent='old-stop')))
  self.assertIsNone(p.settling_stop);self.assertEqual(p.session.deadline,deadline)
  self.assertEqual((p.session.expires,p.session.heartbeat_deadline),lease)
 async def test_poll_visual_exception_during_stop_closes_actual_run(self):
  t,p=await self.make(run=True);p.session.begin_turn();await p.commands();entered,release=await self.old_generation(p);called=asyncio.Event()
  async def fail():called.set();raise WireError('PRIVATE_VISUAL')
  run_task=next(x for x in t.tasks if x.get_coro().__name__=='run')
  with patch.object(p,'poll_visual',fail):
   try:
    await t.command('stop',intent='old-stop');await entered.wait();await asyncio.wait_for(called.wait(),.3)
    release.set()
    done,_=await asyncio.wait({run_task},timeout=.6)
    self.assertTrue(done)
    self.assertTrue(p.closed);self.assertFalse(p.session.active);self.assertIsNone(p.settling_stop)
   finally:release.set()
 async def test_ttl_and_heartbeat_expire_during_real_cancellation_window(self):
  for kind in ('ttl','heartbeat'):
   t,p=await self.make();p.session.begin_turn();await p.commands();entered,release=await self.old_generation(p)
   stop=asyncio.create_task(p.handle(json.dumps(dict(v=2,type='stop',epoch=1,seq=0,intent='old-stop'))));await entered.wait()
   if kind=='ttl':p.session.expires=110.
   else:p.session.heartbeat_deadline=110.
   self.now[0]=111.;monitor=asyncio.create_task(p.monitor())
   try:
    done,_=await asyncio.wait({monitor},timeout=.3);self.assertTrue(done);await monitor
    self.assertFalse(p.session.active)
   finally:
    release.set();await stop;monitor.cancel();await asyncio.gather(monitor,return_exceptions=True)
 async def test_runner_control_and_unknown_failure_enums_never_reflect_content(self):
  from scripts import v2_soak as soak
  t,p=await self.make();receive=asyncio.create_task(t.receive())
  try:
   await t.socket.outgoing.put(json.dumps({'type':'failure','epoch':0,'code':'PRIVATE_CONTROL'}))
   await asyncio.wait_for(t.completed.wait(),.2)
   class PrivateError(RuntimeError):
    def __str__(self):raise AssertionError('exception body must not be accessed')
   result=soak.failure_metadata(PrivateError(),stage='PRIVATE_STAGE',reason='PRIVATE_REASON',transport=t)
   self.assertEqual(result['control'],'unknown');self.assertEqual(result['stage'],'attempt_wait');self.assertEqual(result['reason'],'unknown')
   self.assertNotIn('PRIVATE_',json.dumps(result))
  finally:receive.cancel();await asyncio.gather(receive,return_exceptions=True)
if __name__=='__main__':unittest.main(defaultTest='Independent',verbosity=2)
