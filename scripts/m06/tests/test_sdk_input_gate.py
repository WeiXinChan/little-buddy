import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sdk_input_gate import topology,PrivatePulse,IsolationError,InputGateObserver,GateError,module_ids,safe_failure

def fixture():
 modules=[dict(index=0,name='module-native-protocol-unix'),dict(index=1,name='module-null-sink'),dict(index=2,name='module-null-sink')]
 sinks=[dict(index=i,name=n,owner_module=i+1,driver='module-null-sink.c',monitor_source=n+'.monitor') for i,n in enumerate(('v2_playback','m06_input'))]
 sources=[dict(index=i,name=s['name']+'.monitor',monitor_source=s['name'],owner_module=s['owner_module'],driver='module-null-sink.c') for i,s in enumerate(sinks)]
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

class ActualTopologyTests(unittest.TestCase):
 def actual(self):return json.loads((Path(__file__).parent/'fixtures/pulse16-topology-projected.json').read_text())
 def run_graph(self,data):
  raw=json.loads((Path(__file__).parent/'fixtures/pulse16-modules-projected.json').read_text())['modules']
  short='0\tmodule-native-protocol-unix\t\n1\tmodule-null-sink\t\n2\tmodule-null-sink\t\n'
  def bounded(args,**kw):
   if args==['pactl','list','short','modules']:return short.encode(),dict(status='AVAILABLE')
   return json.dumps(raw if args[-1]=='modules' else data[args[-1]]).encode(),dict(status='AVAILABLE')
  private=object.__new__(PrivatePulse)
  with patch('native_input_metadata.bounded',side_effect=bounded):
   sources=private.pactl('sources');sinks=private.pactl('sinks');mods=private.module_summary(private.pactl('modules'));clients=private.pactl('clients');outputs=private.pactl('source-outputs')
  return topology(sources,sinks,mods,clients,outputs,lambda pid:pid==data['owned_pid'])
 def test_actual_entire_bounded_json_short_pipeline_and_client_pid(self):
  result=self.run_graph(self.actual());self.assertTrue(result['source_output_present']);self.assertTrue(result['qemu_source_outputs'][0]['corked'])
 def test_missing_conflicting_cross_owner_physical_duplicate_unowned_fail(self):
  mutations=[lambda d:d['sources'][0].pop('monitor_source'),lambda d:d['sinks'][0].update(monitor_source='m06_input.monitor'),lambda d:d['sources'][0].update(owner_module=2),lambda d:d['sources'][0].update(driver='module-alsa-source.c'),lambda d:d['sources'].append(dict(index=9,name='alsa_input')),lambda d:d['sources'][0].update(index=1),lambda d:d['sinks'][0].update(owner_module=2),lambda d:d.update(owned_pid=99999999),lambda d:d['source-outputs'][0].update(source=0)]
  for mutation in mutations:
   with self.subTest(mutation=mutation):
    data=self.actual();mutation(data)
    with self.assertRaises((IsolationError,KeyError)):self.run_graph(data)


class ModuleSchemaTests(unittest.TestCase):
 def actual_schema(self):
  return json.loads((Path(__file__).parent/'fixtures/pulse16-modules-projected.json').read_text())['modules']
 def short(self):return '0\tmodule-native-protocol-unix\tauth-anonymous=1\n1\tmodule-null-sink\tsink_name=v2_playback\n2\tmodule-null-sink\tsink_name=m06_input\n'
 def test_official_16_1_json_no_index_cross_checked_with_short_ids(self):
  raw=self.actual_schema()
  with self.assertRaises(KeyError):[m['index'] for m in raw]
  rows=fixture();rows[2]=module_ids(raw,self.short())
  self.assertTrue(topology(*rows,lambda p:p==42)['source_output_present'])
 def test_missing_duplicate_changed_ids_and_non_null_modules_fail_closed(self):
  for short in (self.short().replace('2\t','1\t'),self.short().splitlines()[0],self.short().replace('module-null-sink','module-alsa-source'),self.short().replace('2\t','99\t')):
   with self.assertRaises(IsolationError):
    rows=fixture();rows[2]=module_ids(self.actual_schema(),short);topology(*rows,lambda p:p==42)
  for raw in (self.actual_schema()+[dict(name='module-alsa-source')],self.actual_schema()[1:]):
   with self.assertRaises(IsolationError):module_ids(raw,self.short())
 def test_bounded_bytes_to_module_summary_full_path(self):
  private=object.__new__(PrivatePulse)
  with patch('native_input_metadata.bounded',return_value=(self.short().encode(),dict(status='AVAILABLE'))) as command:
   result=private.module_summary(self.actual_schema())
  self.assertEqual([r['index'] for r in result],[0,1,2]);self.assertEqual(private.schema['fields']['index'],[])
  command.assert_called_once_with(['pactl','list','short','modules'],limit=16384,seconds=.4)
  with patch('native_input_metadata.bounded',return_value=(b'\xff',dict(status='AVAILABLE'))):
   with self.assertRaises(UnicodeDecodeError):private.module_summary(self.actual_schema())
 def test_safe_failure_contains_only_project_location_not_message(self):
  try:module_ids([],self.short())
  except IsolationError as e:
   row=safe_failure(e);self.assertEqual(row['error_class'],'IsolationError');self.assertTrue(row['source']);self.assertEqual(row['isolation_reason'],'MODULE_SCHEMA');self.assertNotIn('message',row)


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
