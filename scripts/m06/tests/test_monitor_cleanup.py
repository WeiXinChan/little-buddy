"""Deterministic owned-producer failure cleanup; never starts Pulse or a recorder."""
import importlib.util,tempfile,threading,json,unittest,subprocess
from pathlib import Path
spec=importlib.util.spec_from_file_location('monitor_probe',Path(__file__).parents[1]/'monitor_probe.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Worker:
 def join(self,_):pass
 def is_alive(self):return True
class Process:
 def __init__(self,slow=False):self.code=None;self.terminate_calls=0;self.kill_calls=0;self.communicate_calls=0;self.slow=slow
 def poll(self):return self.code
 def terminate(self):self.terminate_calls+=1
 def kill(self):self.kill_calls+=1;self.code=-9
 def wait(self,timeout):
  if self.slow and self.code is None:raise subprocess.TimeoutExpired('owned-parec',timeout)
  if self.code is None:self.code=-15
  return self.code
 def communicate(self,timeout):self.communicate_calls+=1;return b'',b'owned-stderr'
class MonitorCleanupTest(unittest.TestCase):
 def test_reader_join_failure_still_terminates_owned_process(self):
  for slow in [False,True]:
   with self.subTest(slow=slow),tempfile.TemporaryDirectory() as d:
    p=m.MonitorProbe.__new__(m.MonitorProbe);p.stop_event=threading.Event();p.worker=Worker();p.process=Process(slow);p.path=Path(d)/'synthetic.s16le';p.path.write_bytes(b'');p.size=0;p.info={}
    with self.assertRaisesRegex(RuntimeError,'bounded monitor consumer'):p.finish()
    self.assertEqual(1,p.process.terminate_calls);self.assertEqual(int(slow),p.process.kill_calls);self.assertEqual(1,p.process.communicate_calls)
    row=json.loads(p.path.with_suffix('.json').read_text());self.assertTrue(row['reader_alive']);self.assertEqual('RuntimeError',row['finish_error']);self.assertIsNotNone(row['exit'])
if __name__=='__main__':unittest.main()
