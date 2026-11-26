import sys,pathlib,json,unittest,tempfile
sys.path.insert(0,str(pathlib.Path.cwd()))
from hashlib import sha256
from types import SimpleNamespace
from scripts import v2_soak_memory as m
from tests.v2.test_soak_memory_worker_validation import worker_fixture,fake_supervisor
class Sampling(unittest.TestCase):
 def test_invalid_sampling_full_report_must_stop_before_next_arm(self):
  with tempfile.TemporaryDirectory() as directory:
   out=pathlib.Path(directory)/'out'
   def fake_child(args,**kwargs):
    result=worker_fixture(args);artifact=pathlib.Path(args[args.index('--artifact')+1]);full=json.loads(artifact.read_bytes())
    full['sampling'].update(errors=1,valid=False,missing_metrics=['backend_rss_bytes'])
    full['resource_collection_valid']=False
    raw=json.dumps(full,sort_keys=True).encode();artifact.write_bytes(raw)
    result['full_report_sha256']=sha256(raw).hexdigest();result['report_structure'].update(file_bytes=len(raw),top_level_fields=len(full))
    return SimpleNamespace(stdout=json.dumps(result).encode())
   raised=False
   with fake_supervisor(fake_child) as calls:
    try:report=m.profile(out,6,30)
    except m.Invalid:raised=True
   terminal=json.loads((out/'result.json').read_text());print('SAMPLING_INVALID_PARENT',json.dumps({'raised':raised,'child_calls':calls.call_count,'status':terminal['status']}))
   self.assertTrue(raised,'full report declares failed/incomplete resource collection; do not continue controls')
   self.assertEqual(calls.call_count,1)
if __name__=='__main__':unittest.main(verbosity=2)
