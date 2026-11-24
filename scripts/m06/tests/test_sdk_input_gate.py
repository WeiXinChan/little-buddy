import copy
from pathlib import Path
import sys
import tempfile
import threading
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sdk_input_gate import topology,PrivatePulse,IsolationError,InputGateObserver,GateError

def fixture():
 modules=[dict(index=0,name='module-native-protocol-unix'),dict(index=1,name='module-null-sink'),dict(index=2,name='module-null-sink')]
 sinks=[dict(index=i,name=n,owner_module=i+1,driver='module-null-sink.c') for i,n in enumerate(('v2_playback','m06_input'))]
 sources=[dict(index=i,name=s['name']+'.monitor',monitor_of_sink=i,owner_module=s['owner_module'],driver='module-null-sink.c') for i,s in enumerate(sinks)]
 clients=[dict(index=1,properties={'application.process.id':'42'})]
 outputs=[dict(index=0,client=1,source=1,corked=False)]
 return [sources,sinks,modules,clients,outputs]

class IsolationTests(unittest.TestCase):
 def test_only_private_two_null_monitors_owned_qemu(self):
  r=topology(*fixture(),lambda pid:pid==42)
  self.assertEqual(r['qemu_source_outputs'][0]['source'],'m06_input.monitor')
 def test_hardware_source_module_or_unowned_client_rejected(self):
  for index,change in [(0,lambda x:x.append(dict(index=2,name='alsa_input',driver='module-alsa-source.c'))),(2,lambda x:x.append(dict(index=3,name='module-alsa-source'))),(4,lambda x:x[0].update(source=0))]:
   rows=fixture();change(rows[index])
   with self.assertRaises(IsolationError):topology(*rows,lambda pid:pid==42)
  with self.assertRaises(IsolationError):topology(*fixture(),lambda _:False)
 def test_non_gha_or_non_synthetic_platform_never_probes_proc(self):
  for env in ({},{'GITHUB_ACTIONS':'true'},{'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'self-hosted'}):
   with self.assertRaises(IsolationError):PrivatePulse(env)

class ObserverTests(unittest.TestCase):
 def make(self,initial=False,prove=lambda:dict(private=True)):
  directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
  state=[initial];writes=[];seen=threading.Event()
  def read():
   value=state[0]
   if value:seen.set()
   return value
  def write(v):writes.append(v);state[0]=v
  p=InputGateObserver(read,write,prove,Path(directory.name)/'gate.json',ready_delay=0)
  def cleanup():
   p.stop.set()
   if p.thread.ident is not None:p.thread.join(3)
   self.assertFalse(p.thread.is_alive())
  self.addCleanup(cleanup)
  return p,state,writes,seen
 def test_false_once_enabled_then_join_and_restore_false(self):
  p,state,writes,seen=self.make();p.begin();p.first_packet()
  self.assertTrue(seen.wait(2));p.finish()
  self.assertEqual(writes,[True,False]);self.assertFalse(state[0]);self.assertTrue(p.row['restored_false']);self.assertFalse(p.thread.is_alive())
 def test_already_true_has_no_redundant_enable(self):
  p,state,writes,seen=self.make(True);p.begin();p.first_packet()
  self.assertTrue(seen.wait(2));p.finish();self.assertEqual(writes,[False])
 def test_begin_failure_never_joins_unstarted_thread_or_enables(self):
  def fail():raise IsolationError('fixed code')
  p,state,writes,_=self.make(prove=fail)
  with self.assertRaises(IsolationError):p.begin()
  with self.assertRaises(GateError):p.finish()
  self.assertEqual(writes,[False]);self.assertTrue(p.row['restored_false'])
 def test_stream_isolation_failure_stays_off_and_restores(self):
  calls=[0]
  def proof():
   calls[0]+=1
   if calls[0]>1:raise IsolationError('changed')
   return dict(private=True)
  p,state,writes,_=self.make(prove=proof);p.begin();p.first_packet();p.thread.join(2)
  with self.assertRaises(GateError):p.finish()
  self.assertNotIn(True,writes);self.assertFalse(state[0]);self.assertTrue(p.row['observer_stopped'])
 def test_stopping_during_proof_cannot_late_enable(self):
  entered=threading.Event();release=threading.Event();calls=[0]
  def proof():
   calls[0]+=1
   if calls[0]>1:entered.set();self.assertTrue(release.wait(2))
   return dict(private=True)
  p,state,writes,_=self.make(prove=proof);p.begin();p.first_packet();self.assertTrue(entered.wait(2))
  p.stop.set();release.set();p.thread.join(2)
  with self.assertRaises(GateError):p.finish()
  self.assertNotIn(True,writes)

 def test_initial_true_then_false_is_observed_without_late_toggle(self):
  p,state,writes,seen=self.make(True);observed=threading.Event();save=p.save
  def journal(event,**fields):
   save(event,**fields)
   if event=='GATE_FALSE_OBSERVED_NO_RETRY':observed.set()
  p.save=journal;p.begin();p.first_packet()
  self.assertTrue(seen.wait(2));state[0]=False
  self.assertTrue(observed.wait(2));p.finish();self.assertNotIn(True,writes)
