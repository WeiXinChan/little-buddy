import json
import sys
import tempfile
import types
import os
import io
import stat
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import enumeration_metadata as e
from native_readonly import NativeReadOnly, Unavailable

OK=dict(status='AVAILABLE',exit_code=0,eof=True,capped=False)
class EnumerationTests(unittest.TestCase):
 def test_alsa_states_and_no_raw_unknown_body(self):
  for text,expected in [('', 'EMPTY'),('--- no soundcards ---\n','NO_SOUNDCARDS'),('secret bearer arbitrary','UNRECOGNISED')]:
   result=e.alsa(e.CARDS,text);self.assertEqual(result['state'],expected);self.assertNotIn('secret',json.dumps(result))
  cards=e.alsa(e.CARDS,' 0 [Intel          ]: HDA-Intel - HDA Intel\n                      HDA Intel at 0xfebd0000 irq 20\n')
  self.assertEqual(cards['cards'][0],dict(card=0,id='Intel',driver='HDA-Intel'))
  pcm=e.alsa(e.PCM,'00-00: ALC PCM : playback 1 : capture 1\n');self.assertTrue(pcm['pcm'][0]['capture'])
  path='/proc/asound/card0/pcm0c/sub0/status'
  self.assertEqual(e.alsa(path,'state: RUNNING\nowner_pid: 81\nhw_ptr: 320\nappl_ptr: 160\n')['values']['hw_ptr'],320)
  self.assertTrue(e.alsa(path,'closed')['closed'])
  self.assertEqual(e.alsa(path,'state: SECRET')['state'],'UNRECOGNISED')
 def test_kernel_projection_no_build_identity_body(self):
  self.assertEqual(e.kernel('version','Linux version 6.12.4-android16 (builder@private) #1 SMP')['release'],'6.12.4-android16')
  self.assertNotIn('private',json.dumps(e.kernel('version','Linux version 6.12.4-android16 (builder@private) #1 SMP')))
  self.assertEqual(e.kernel('release','unknown credentials')['state'],'UNRECOGNISED')
 def test_pci_audio_driver_and_card_link(self):
  text='0000:00:1b.0 0x040300 0x8086 0x2668 /sys/bus/pci/drivers/snd_hda_intel\n'
  self.assertEqual(e.pci(text)['devices'][0]['bdf'],'0000:00:1b.0')
  for bad in (text+text,text.replace('040300','030000'),text.replace('00:1b.0','00:ff.8'),text.replace('/sys/bus/pci/drivers/snd_hda_intel','/etc/secret')):
   self.assertEqual(e.pci(bad)['state'],'UNRECOGNISED')
  self.assertEqual(e.card_links('card0 /sys/devices/pci0000:00/0000:00:1b.0')['links'],[dict(card=0,bdf='0000:00:1b.0')])
  self.assertEqual(e.card_links('card0 /private/path')['state'],'UNRECOGNISED')
 def test_transport_failures_truncation_permissions_timeout_and_budget(self):
  for raw,meta,expected in [(b'',dict(OK,exit_code=44),'UNREADABLE'),(b'',dict(OK,exit_code=1),'COMMAND_FAILED'),(b'',dict(OK,eof=False),'COMMAND_FAILED'),(b'bad',dict(OK,capped=True),'TRUNCATED'),(b'\xff',OK,'UNRECOGNISED')]:
   self.assertEqual(e.read_row(lambda *a,**k:(raw,meta),'fixed',lambda t:e.alsa(e.CARDS,t),8,clock=lambda:0)['state'],expected)
  run=Mock();self.assertEqual(e.read_row(run,'fixed',lambda t:{},0,clock=lambda:0)['reason'],'TOTAL_BUDGET');run.assert_not_called()
  run=Mock(side_effect=TimeoutError('never retain message'))
  self.assertEqual(e.read_row(run,'fixed',lambda t:{},8,clock=lambda:0)['reason'],'RUNNER_EXCEPTION')
  ticks=iter([0,9]);self.assertEqual(e.read_row(lambda *a,**k:(b'--- no soundcards ---',OK),'fixed',lambda t:e.alsa(e.CARDS,t),8,clock=lambda:next(ticks))['reason'],'TOTAL_BUDGET')
 def test_full_mock_collection_no_authorization_and_fixed_paths(self):
  path='/proc/asound/card0/pcm0c/sub0/status'
  responses={e.file_command(e.CARDS):b'--- no soundcards ---',e.file_command(e.PCM):b'',e.PATHS:path.encode(),e.file_command(path):b'closed','uname -r':b'6.12.4',e.file_command('/proc/version'):b'Linux version 6.12.4 private build',e.PCI:b'',e.LINKS:b'',e.MODULE:b'ABSENT'}
  seen=[]
  def run(argv,**kw):
   seen.append(argv);self.assertLessEqual(kw['seconds'],1);self.assertLessEqual(kw['limit'],8192)
   return responses[argv[-1]],OK
  result=e.collect(run,8,clock=lambda:0)
  self.assertFalse(result['fixture_authorization']);self.assertEqual(result['mode'],'METADATA_ONLY')
  self.assertEqual(result['alsa'][e.CARDS]['state'],'NO_SOUNDCARDS');self.assertFalse(result['snd_hda_intel']['present'])
  self.assertNotIn('private',json.dumps(result));self.assertEqual(len(seen),9)
  with self.assertRaises(ValueError):e.file_command('/proc/config.gz')
 def test_native_glue_never_roots_and_rechecks_identity_objects(self):
  with tempfile.TemporaryDirectory() as d:
   native=NativeReadOnly(Path(d),run=Mock(),proof=types.SimpleNamespace(verify_metadata_only=lambda:dict(proof_scope='BASE_METADATA_ONLY')))
   self.assertEqual(native.enumeration_metadata()['reason'],'ROOT_OR_HAL_UNAVAILABLE');native.run.assert_not_called()
   native.rooted=True;native.hal={'pid':81};native.objects=['fixed']
   native.guard=Mock();native.get_objects=Mock(return_value=['fixed'])
   with patch('enumeration_metadata.collect',return_value=dict(mode='METADATA_ONLY',fixture_authorization=False)) as collect:
    self.assertTrue(native.enumeration_metadata()['identity_rechecked']);self.assertEqual(native.guard.call_count,2);collect.assert_called_once()
   native.guard=Mock(side_effect=Unavailable('PID_REPLACED'))
   with patch('enumeration_metadata.collect') as collect:
    self.assertEqual(native.enumeration_metadata()['reason'],'PID_REPLACED');collect.assert_not_called()
   native.run.assert_not_called() # no actual command or root in this test

 def test_identity_or_object_change_retains_typed_facts_without_authorization(self):
  with tempfile.TemporaryDirectory() as d:
   native=NativeReadOnly(Path(d),run=Mock(),proof=types.SimpleNamespace(verify_metadata_only=lambda:dict(proof_scope='BASE_METADATA_ONLY')));native.rooted=True;native.hal={'pid':81};native.objects=['fixed'];native.guard=Mock()
   native.get_objects=Mock(side_effect=[['fixed'],['different']])
   with patch('enumeration_metadata.collect',return_value=dict(mode='METADATA_ONLY',fixture_authorization=False,alsa={e.CARDS:e.state('NO_SOUNDCARDS')})):
    result=native.enumeration_metadata()
   self.assertEqual(result['reason'],'OBJECT_SET_CHANGED');self.assertFalse(result['identity_rechecked']);self.assertFalse(result['fixture_authorization'])
   self.assertEqual(result['alsa'][e.CARDS]['state'],'NO_SOUNDCARDS');native.run.assert_not_called()
 def test_shell_plans_syntax_only_and_no_arbitrary_path(self):
  import subprocess
  for cmd in (e.PCI,e.PATHS,e.LINKS,e.MODULE,e.file_command(e.CARDS)):
   subprocess.run(['bash','-n'],input=cmd,text=True,check=True)
  for path in ('/proc/config.gz','/sys/bus/pci/devices/0000:00:1b.0/config','/proc/asound/card8/pcm0c/sub0/status','/proc/asound/cards; id'):
   with self.assertRaises(ValueError):e.file_command(path)

 def test_default_native_real_metadata_view_preserves_full_private_checks_without_hda(self):
  from sdk_input_gate import PrivatePulse, IsolationError
  from test_sdk_input_gate import fixture
  from hda_guard import HdaStop
  private=object.__new__(PrivatePulse)
  private.uid=1000;private.pulse=40;private.root=42;private.env={'M06_REQUIRE_HDA':'1'}
  private.directory=Path('/synthetic/v2-avd');private.socket=private.directory/'pulse.sock';private.server='unix:'+str(private.socket)
  sources,sinks,modules,clients,outputs=fixture()
  private.pactl=lambda kind:dict(sources=sources,sinks=sinks,modules=modules,clients=clients,**{'source-outputs':outputs})[kind]
  def summary(rows):private.schema={'count':len(rows)};return rows
  private.module_summary=summary
  expected={'PULSE_SERVER':private.server,'QEMU_PA_SERVER':private.server,'PULSE_SOURCE':'m06_input.monitor','QEMU_PA_SOURCE':'m06_input.monitor','PULSE_SINK':'v2_playback','QEMU_PA_SINK':'v2_playback'}
  def fields(path):
   name=str(path)
   if name=='/proc/40/cmdline':return iter(['pulseaudio','-n','-F',str(private.directory/'pulse.pa')])
   if name=='/proc/42/cmdline':return iter(['qemu-system-x86_64']) # No soundhw/feature host evidence.
   if name=='/proc/42/environ':return iter([k+'='+v for k,v in expected.items()])
   raise AssertionError('unexpected synthetic proc read')
  def fakepath(value):
   name=str(value);obj=Mock()
   if name.endswith(('/cmdline','/environ')):return Path(name)
   if name.endswith('/exe'):obj.resolve.return_value.name='pulseaudio' if '/40/' in name else 'qemu-system-x86_64'
   elif name=='/proc/net/unix':obj.open.return_value=io.StringIO('a b c d e f 5 '+str(private.socket)+'\n')
   elif name=='/proc/40/fd':obj.iterdir.return_value=[Path('/proc/40/fd/1')]
   else:raise AssertionError('unexpected synthetic path')
   return obj
  with tempfile.TemporaryDirectory() as d:
   native=NativeReadOnly(Path(d),run=Mock());native.rooted=True;native.hal={'pid':81};native.objects=['fixed'];native.guard=Mock();native.get_objects=Mock(return_value=['fixed'])
   with patch('sdk_input_gate.owner',return_value=True),patch('sdk_input_gate.descendant',return_value=True),patch('sdk_input_gate.Path',side_effect=fakepath),patch('sdk_input_gate.nul_fields',side_effect=fields),patch('sdk_input_gate.os.readlink',return_value='socket:[5]'),patch.object(Path,'stat',return_value=types.SimpleNamespace(st_mode=stat.S_IFSOCK|0o600,st_uid=1000)),patch('native_readonly.PrivatePulse',return_value=private),patch('enumeration_metadata.collect',return_value={'alsa':{e.CARDS:e.state('NO_SOUNDCARDS')}}) as collect:
    with self.assertRaises(HdaStop):private.verify() # FULL really rejects this host representation.
    row=native.enumeration_metadata()
    self.assertTrue(row['identity_rechecked']);self.assertEqual(row['private_proof_scope'],'BASE_METADATA_ONLY');self.assertFalse(row['fixture_authorization']);collect.assert_called_once()
    native.guard.reset_mock();collect.reset_mock()
    with patch('sdk_input_gate.owner',return_value=False):
     failed=native.enumeration_metadata()
    self.assertEqual(failed['status'],'UNAVAILABLE');collect.assert_not_called();native.guard.assert_not_called();native.run.assert_not_called()

 def test_explicit_wrong_scope_fails_before_any_native_query(self):
  with tempfile.TemporaryDirectory() as d:
   native=NativeReadOnly(Path(d),run=Mock());native.rooted=True;native.hal={'pid':81};native.guard=Mock()
   for result in ({},{'proof_scope':'FULL_AUDIO_ISOLATION'},None):
    with patch('enumeration_metadata.collect') as collect:
     row=native.enumeration_metadata(metadata_proof=types.SimpleNamespace(verify=lambda:result))
     self.assertEqual(row['reason'],'METADATA_PROOF_SCOPE');self.assertFalse(row['fixture_authorization']);collect.assert_not_called()
   native.guard.assert_not_called();native.run.assert_not_called()

 def test_pci_total_bdf_limit_precedes_reads_and_discards_partial_audio(self):
  import subprocess
  # Execute only a synthetic local directory tree, never /sys, adb or a service.
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)
   for n in range(65):
    node=root/f'0000:{n//32:02x}:{n%32:02x}.0';node.mkdir();(node/'class').write_text('0x030000')
   cmd=e.PCI.replace('/sys/bus/pci/devices/*',str(root)+'/*')
   result=subprocess.run(['bash','-c',cmd],capture_output=True,timeout=2)
   self.assertEqual(result.returncode,46)
   row=e.read_row(lambda *a,**kw:(result.stdout,dict(OK,exit_code=result.returncode)),e.PCI,e.pci,8,clock=lambda:0)
   self.assertEqual(row,dict(state='COMMAND_FAILED',reason='PCI_BDF_LIMIT'))
   (root/'0000:02:00.0'/'class').unlink();(root/'0000:02:00.0').rmdir()
   normal=subprocess.run(['bash','-c',cmd],capture_output=True,timeout=2)
   self.assertEqual(normal.returncode,0);self.assertEqual(e.pci(normal.stdout.decode())['state'],'EMPTY')
