import sys,pathlib,ast,json,io,tarfile,unittest,tempfile,os,stat
sys.path.insert(0,str(pathlib.Path.cwd()))
from contextlib import contextmanager
from unittest.mock import patch
from types import SimpleNamespace
from scripts import v2_soak_memory as m
class Independent(unittest.TestCase):
 def test_malformed_child_metadata_must_leave_terminal_result_not_in_progress(self):
  @contextmanager
  def fake_lock():yield 42
  buf=io.BytesIO()
  with tarfile.open(fileobj=buf,mode='w'):pass
  result={'cleanup':{},'failures':0,'attempted':6}
  with tempfile.TemporaryDirectory() as d:
   out=pathlib.Path(d)/'out'
   with patch.object(m,'heavy_lock',fake_lock),patch.object(m.subprocess,'check_output',return_value=buf.getvalue()),patch.object(m.subprocess,'run',return_value=SimpleNamespace(stdout=json.dumps(result).encode())) as child:
    with self.assertRaises(Exception):m.profile(out,6,30)
   self.assertEqual(child.call_count,1)
   status=json.loads((out/'result.json').read_text())['status'];print('MALFORMED_CHILD_TERMINAL',status)
   self.assertNotEqual(status,'in_progress','rejected child metadata must persist final failed/unknown state')
 def test_memory_controls_with_different_retained_sample_workload_not_comparable(self):
  tree=ast.parse(pathlib.Path(m.__file__).read_text())
  node=next(n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='comparable' for t in n.targets))
  expression=compile(ast.Expression(node.value),'<frozen comparison expression>','eval')
  rows=[dict(input_schedule_sha256='same',attempted=6,output_schedule_sha256='same',model_stage_calls={'plan':6},reported_sample_rows=n) for n in [100,200,200]]
  comparable=eval(expression,{'json':json},dict(actual=rows));print('DIFFERENT_SAMPLE_COUNTS',comparable)
  self.assertFalse(comparable,'memory control workload includes retained sample dictionaries, not just model schedule')
 def test_busy_lock_refuses_without_real_fd_lock_or_process(self):
  import fcntl
  parent=SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_uid=0,st_gid=0)
  file=SimpleNamespace(st_mode=stat.S_IFREG|0o644,st_uid=0,st_gid=0)
  with patch.object(pathlib.Path,'lstat',return_value=parent),patch.object(m.os,'open',return_value=42) as opened,patch.object(m.os,'fstat',return_value=file),patch.object(m.os,'close') as closed,patch.object(fcntl,'flock',side_effect=BlockingIOError),patch.object(m.subprocess,'run',side_effect=AssertionError('no process')):
   with self.assertRaises(m.Invalid) as caught:
    with m.heavy_lock():self.fail('busy lock admitted')
   self.assertEqual(str(caught.exception),'lock_busy');self.assertTrue(opened.call_args.args[1]&os.O_NOFOLLOW);closed.assert_called_once_with(42)
if __name__=='__main__':unittest.main(verbosity=2)
