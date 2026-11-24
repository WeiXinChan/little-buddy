"""Host-only fault injection; no Android, Pulse, audio playback or cloud."""
import importlib.util,json,subprocess,tempfile,unittest,wave
from pathlib import Path
spec=importlib.util.spec_from_file_location('route_evidence',Path(__file__).parents[1]/'route_evidence.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
class Process:
 pid=123
 def __init__(self,code=0,timeout=False):self.returncode=None;self.code=code;self.timeout=timeout
 def poll(self):return self.returncode
 def terminate(self):self.returncode=-15
 def kill(self):self.returncode=-9
 def communicate(self,timeout):
  if self.timeout and self.returncode is None:raise subprocess.TimeoutExpired('paplay',timeout,output='partial',stderr='delayed')
  if self.returncode is None:self.returncode=self.code
  return ('','actual-stderr')
class RouteJournalTest(unittest.TestCase):
 def run_case(self,kind):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);wav=root/'fixture.wav'
   with wave.open(str(wav),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(bytes(320))
   p=Process(code=7 if kind=='playback_nonzero' else 0,timeout=kind=='playback_timeout');calls=0
   def start(*args,**kwargs):
    self.assertTrue((root/'mic-route-nonce.json').is_file())
    if kind=='spawn':raise OSError('synthetic spawn fault')
    return p
   def query(cmd,**kwargs):
    nonlocal calls
    calls+=1
    if calls==2 and kind=='query_timeout':raise subprocess.TimeoutExpired(cmd,5,output='partial-route',stderr='query-late')
    value='not-json' if calls==2 and kind=='parse' else '[]'
    return subprocess.CompletedProcess(cmd,9 if calls==2 and kind=='query_nonzero' else 0,value,'query-stderr')
   error=None
   try:r.play_fixture(wav,dict(nonce='nonce',sha256='validated-test',name='fixture'),root,start=start,query=query,sleep=lambda _:None)
   except Exception as e:error=e
   saved=json.loads((root/'mic-route-nonce.json').read_text())
   self.assertTrue(saved['stages']);self.assertIn('source',saved)
   if kind=='success':self.assertIsNone(error);self.assertEqual(0,saved['playback_exit'])
   else:self.assertIsNotNone(error);self.assertIn('failed_stage',saved)
   if kind in ('parse','query_nonzero','query_timeout'):
    self.assertIn('clients',saved);self.assertEqual([],saved['clients']['data'])
   if kind=='parse':self.assertEqual('not-json',saved['sources']['stdout'])
   if kind=='query_nonzero':self.assertEqual(9,saved['sources']['exit'])
   if kind=='query_timeout':self.assertTrue(saved['timeout']);self.assertEqual('partial-route',saved['failure_stdout'])
   if kind=='playback_nonzero':self.assertEqual(7,saved['playback_exit'])
   if kind=='playback_timeout':self.assertTrue(saved['timeout']);self.assertEqual('delayed',saved['failure_stderr']);self.assertEqual(-15,saved['playback_exit'])
   if kind!='spawn':self.assertEqual('actual-stderr',saved['playback_stderr']);self.assertIsNotNone(p.poll())
 def test_all_stage_failures_retain_prior_evidence(self):
  for kind in ['success','spawn','query_timeout','query_nonzero','parse','playback_timeout','playback_nonzero']:
   with self.subTest(kind=kind):self.run_case(kind)
if __name__=='__main__':unittest.main()
