import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from source_calibration import pair,transport_complete,ENTER_SHA,PROTO_SHA

class PairTest(unittest.TestCase):
 def ready(self,source):return dict(source=source,gates_accepted=True,finished=True,released=True,stopped=True,worker_done=True,lease_available=True,recording=False,transport_complete=True,test_exit=1,live_enter=False)
 def test_low_signal_or_live_failure_does_not_prevent_second_arm(self):
  calls=[]
  def arm(s):calls.append(s);return self.ready(s)
  self.assertEqual(pair(arm)['status'],'PAIR_EXECUTED');self.assertEqual(calls,[7,6])
 def test_each_real_ownership_or_identity_gate_stops_second_arm(self):
  for field in ('gates_accepted','finished','released','stopped','worker_done','lease_available','recording'):
   calls=[]
   def arm(s):
    calls.append(s);r=self.ready(s);r[field]=(field=='recording');return r
   self.assertEqual(pair(arm)['status'],'OWNERSHIP_OR_GATE_STOP');self.assertEqual(calls,[7])

 def test_not_ready_init_gate_never_executes_source6(self):
  calls=[]
  def arm(s):
   calls.append(s);r=self.ready(s);r['gates_accepted']=False;return r
  self.assertEqual(pair(arm)['unexecuted'],[6]);self.assertEqual(calls,[7])
 def test_rpc_or_packet_failure_never_executes_source6(self):
  calls=[]
  def arm(s):
   calls.append(s);r=self.ready(s);r['transport_complete']=False;return r
  self.assertEqual(pair(arm)['unexecuted'],[6]);self.assertEqual(calls,[7])
 def test_transport_receipt_binds_exact_fixture_nonce_format_and_count(self):
  r=dict(nonce='owned',name='enter',sha256=ENTER_SHA,backend='EmulatorController.injectAudio',proto_sha256=PROTO_SHA,stage='inject_completed',rpc_code='OK',packets=218,playback_exit=0,source_samples=64960,rate=16000,channels=1,sample_format='s16le',mode='MODE_UNSPECIFIED',drain_ms=300,packet_ms=20,host_mic=False)
  self.assertTrue(transport_complete(r,'owned'))
  for k,v in dict(nonce='other',sha256='other',stage='rpc_failed',rpc_code='CANCELLED',packets=217,rate=48000,channels=2,host_mic=True).items():
   self.assertFalse(transport_complete(dict(r,**{k:v}),'owned'))
