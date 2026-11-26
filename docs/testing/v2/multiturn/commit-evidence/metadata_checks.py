import asyncio,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent/'source'))
from scripts import v2_multiturn_probe as probe
from tests.v2 import test_multiturn_probe as fixtures
from tests.v2.test_m05 import Model,plan
from backend.v2.companion import UnifiedProviders,CompanionPolicy
class Metadata(unittest.IsolatedAsyncioTestCase):
 async def test_old_game_must_not_be_reported_as_current_turn_commit(self):
  calls=[0];snapshots=[]
  class Manager:
   def __init__(self,index):self.index=index
   async def __aenter__(self):
    async def frames():yield b'\x01\x00'*4800
    return frames()
   async def __aexit__(self,*args):
    if self.index==3:await asyncio.sleep(.65)
  class Speech:
   def synthesize(self,*args):calls[0]+=1;return Manager(calls[0])
  m=Model(plan());m.next_plan.update(mode='story',rules='轮流旧规则',roles=['小猫'],anchors={},sentences=['第一句。','第二句。'])
  p=UnifiedProviders(Speech(),m)
  def observe(label,snapshot):
   snapshots.append(snapshot)
   if len(snapshots)==1:m.next_plan['rules']='轮流新规则'
  report=await probe.run_case(fixtures.CASE,p,observer=observe)
  second=report['turns'][1];self.assertEqual(len(snapshots),2);self.assertEqual(snapshots[1]['game']['rules'],'轮流旧规则')
  self.assertFalse(second['checks']['delivery']);self.assertFalse(second['quality_assessable']);self.assertFalse(report['cleanup']['confirmed']);self.assertEqual(p.probe_cleanup_handle.pending(),())
  print('CROSS_TURN game_still_old=true new_rule_not_committed=true reported_game_committed='+str(second['delivery_metadata']['game_committed']))
  self.assertFalse(second['delivery_metadata']['game_committed'],'old committed game is not this failed turn proposal commit')
 async def test_telemetry_does_not_suppress_body_cancel_or_exit_failure(self):
  for mode in ['cancel','exit_failure','normal']:
   outcomes=[]
   for cls in [probe.ProductionVoicePeer,probe.VoicePeer]:
    calls=[]
    class Manager:
     async def __aenter__(self):calls.append('enter');return 7
     async def __aexit__(self,*args):
      calls.append('exit')
      if mode=='exit_failure':raise ValueError('PRIVATE_SECRET_SENTINEL')
      return True # production ignores suppression, diagnostic must preserve that behavior
    peer=cls(probe.Sink(),fixtures.Probe().providers(),CompanionPolicy())
    error=None
    try:
     async with peer.resource(Manager()) as value:
      self.assertEqual(value,7)
      if mode=='cancel':raise asyncio.CancelledError()
    except BaseException as e:error=type(e).__name__
    self.assertEqual(calls,['enter','exit']);self.assertFalse(peer.retired_tasks)
    outcomes.append((error,peer.quarantined))
    if cls is probe.VoicePeer:self.assertNotIn('PRIVATE_SECRET_SENTINEL',str(peer.probe_resources))
   self.assertEqual(outcomes[0],outcomes[1])
 async def test_audio_byte_count_is_transport_coordinate_only_not_playback(self):
  sink=probe.Sink(ack=False)
  await sink.send('{"type":"audio","start":100,"end":420,"pcm":"SYNTHETIC_NOT_AUDIO"}')
  self.assertEqual(sink.audio_bytes,640);self.assertEqual(sink.acks,0);self.assertEqual(sink.events,[{'type':'audio'}])
if __name__=='__main__':unittest.main(defaultTest='Metadata',verbosity=2)
