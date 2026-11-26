import sys,unittest,asyncio,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent/'source'))
from scripts import v2_soak as soak
class Independent(unittest.IsolatedAsyncioTestCase):
 def limits(self,**kw):
  d=dict(duration=.18,interval=.1,sample_interval=.18,attempt_timeout=.15,max_attempts=1);d.update(kw);return soak.Limits(**d)
 async def test_real_active_operation_peak_must_not_disappear_between_samples(self):
  transports=[];witness=[];real_transport=soak.BackendTransport;real_model=soak.OfflineModel
  class Transport(real_transport):
   def __init__(self,*a):super().__init__(*a);transports.append(self)
  class Model(real_model):
   async def complete(self,*a,**kw):
    witness.append(transports[0].sample()['active_operations']);await asyncio.sleep(.03)
    return await super().complete(*a,**kw)
  with patch.object(soak,'BackendTransport',Transport),patch.object(soak,'OfflineModel',Model):r=await soak.run_soak(self.limits())
  self.assertGreater(max(witness),0);self.assertTrue(r['cleanup']['confirmed']);self.assertEqual(r['delivered'],1)
  print('ACTIVE_PEAK',{'witness':max(witness),'reported_peak':r['resource_trends']['active_operations']['maximum'],'samples':[s['active_operations'] for s in r['resource_samples']]})
  self.assertGreater(r['resource_trends']['active_operations']['maximum'],0,'actual active operations must have a recorded active sample/peak, not only idle samples')
 async def test_attempt_cap_standby_is_not_mixed_interaction_acceptance(self):
  start=time.monotonic();r=await soak.run_soak(self.limits())
  self.assertGreaterEqual(time.monotonic()-start,.18);self.assertEqual(r['stop_reason'],'attempt_cap')
  self.assertGreater(r['standby_seconds'],r['active_attempt_seconds'])
  self.assertFalse(r['p14_verified'] or r['full_acceptance']);self.assertIsNone(r['effective_interaction_seconds'])
  self.assertIn('tls_network_observation',r['missing']);self.assertEqual(r['layer'],'synthetic_text_real_voicepeer_json_duplex_simulated_ack')
 async def test_unconfirmed_cleanup_cannot_restore_provider_or_claim_pass(self):
  real=soak.BackendTransport.close;seen=[]
  async def unconfirmed(transport):
   ok,pending=await real(transport);self.assertTrue(ok);self.assertFalse(pending)
   return False,set() # completed tasks alone are not release proof
  real_init=soak.BackendTransport.__init__
  def capture(transport,p):seen.append(p);real_init(transport,p)
  with patch.object(soak.BackendTransport,'close',unconfirmed),patch.object(soak.BackendTransport,'__init__',capture):r=await soak.run_soak(self.limits())
  self.assertFalse(r['cleanup']['confirmed'] or r['cleanup']['provider_reusable'] or r['p14_verified'] or r['full_acceptance'])
  self.assertIsNotNone(seen[0].probe_cleanup_handle);self.assertFalse(seen[0].probe_cleanup_handle.open)
  self.assertFalse(seen[0].probe_cleanup_handle.pending())
if __name__=='__main__':unittest.main(defaultTest='Independent',verbosity=2)
