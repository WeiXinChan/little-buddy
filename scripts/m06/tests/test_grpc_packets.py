"""Actual SDK37310 proto serialization; no running emulator/RPC claim."""
import importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('grpc_mic',Path(__file__).parents[1]/'grpc_mic.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class PacketTests(unittest.TestCase):
 def test_twenty_ms_pacing_and_exact_drain(self):
  clock=[0.0];sleep=[]
  def wait(t):sleep.append(t);clock[0]+=t
  def packet(**kw):return kw
  source=bytes(range(256))*125 #32000 bytes exactly one second
  packets=list(m.packet_plan(source,16000,packet,'fixed',lambda:clock[0],wait))
  self.assertEqual(65,len(packets));self.assertEqual(source+bytes(9600),b''.join(p['audio'] for p in packets));self.assertTrue(all(len(p['audio'])==640 for p in packets));self.assertAlmostEqual(1.28,clock[0]);self.assertTrue(all(t<=.020001 for t in sleep))
 def test_no_fast_catchup_when_beyond_buffer_safety_margin(self):
  clock=[0.0]
  g=m.packet_plan(bytes(1280),16000,lambda **kw:kw,'fixed',lambda:clock[0],lambda _:None)
  next(g);clock[0]=.3
  with self.assertRaisesRegex(RuntimeError,'pacing'):next(g)
 def test_oversleep_500ms_never_yields_stale_second_packet(self):
  clock=[0.0]
  def oversleep(t):clock[0]+=t+.5
  packets=m.packet_plan(bytes(1280),16000,lambda **kw:kw,'fixed',lambda:clock[0],oversleep)
  next(packets)
  with self.assertRaisesRegex(RuntimeError,'pacing'):next(packets)
 def test_total_deadline_is_checked_after_sleep(self):
  clock=[0.0]
  def wait(t):clock[0]+=t
  packets=m.packet_plan(bytes(1280),16000,lambda **kw:kw,'fixed',lambda:clock[0],wait,deadline=.01)
  next(packets)
  with self.assertRaises(m.InjectionTimingError) as failure:next(packets)
  self.assertEqual('STREAM_DEADLINE',failure.exception.reason)
 def test_serialization_delay_is_checked_before_yield(self):
  clock=[0.0]
  def slow_packet(**kw):clock[0]+=.5;return kw
  packets=m.packet_plan(bytes(1280),16000,slow_packet,'fixed',lambda:clock[0],lambda _:None)
  with self.assertRaises(m.InjectionTimingError):next(packets)
 def test_fixed_600ms_prefix_is_only_zeros_and_preserves_entire_source(self):
  clock=[0.0]
  def wait(t):clock[0]+=t
  source=bytes(range(256))*int(129920/256)+bytes(129920%256)
  packets=list(m.packet_plan(source,16000,lambda **kw:kw,'fixed',lambda:clock[0],wait,deadline=7.06,prefix_ms=600))
  data=b''.join(p['audio'] for p in packets)
  self.assertEqual(len(packets),248)
  self.assertEqual(data[:19200],bytes(19200));self.assertEqual(data[19200:19200+len(source)],source);self.assertEqual(data[-9600:],bytes(9600))
 def test_prefix_does_not_renew_original_deadline(self):
  clock=[0.0]
  def wait(t):clock[0]+=t
  g=m.packet_plan(bytes(1280),16000,lambda **kw:kw,'fixed',lambda:clock[0],wait,deadline=.01,prefix_ms=600)
  next(g)
  with self.assertRaises(m.InjectionTimingError) as e:next(g)
  self.assertEqual(e.exception.reason,'STREAM_DEADLINE')
if __name__=='__main__':unittest.main()
