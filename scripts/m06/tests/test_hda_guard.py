import copy,json,os,subprocess,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
from hda_guard import *
from sdk_input_gate import nul_fields,IsolationError
from sdk_gate_calibration import FINGERPRINT

META=dict(identity_ok=True,known_stub=False,properties={'ro.build.fingerprint':dict(value=FINGERPRINT)})

def installed(root):
 files={'emulator/source.properties':'Pkg.Revision=37.3.10\nPkg.BuildId=16970787\nUnused.Secret=DO_NOT_EXPORT\n','emulator/lib/advancedFeatures.ini':'# declared\nVirtioSndCard = on\nUnrelated = off\n','system-images/android-36/google_apis/x86_64/source.properties':'AndroidVersion.ApiLevel=36\nSystemImage.Abi=x86_64\nSystemImage.TagId=google_apis\n','system-images/android-36/google_apis/x86_64/advancedFeatures.ini':'VirtioSndCard = on\n'}
 for name,value in files.items():
  path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value)

def guest():return dict(status='AVAILABLE',root_uid=0,before=dict(status='AVAILABLE',alsa=dict(status='AVAILABLE',fields=['ALSA_PATH /proc/asound/cards','0 [Intel]: HDA-Intel - HDA Intel']),drivers=dict(status='AVAILABLE',fields=[dict(card='card0',driver_path='/sys/bus/pci/drivers/snd_hda_intel')])))

class HdaGuardTests(unittest.TestCase):
 def directory(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);return Path(tmp.name)
 def test_installed_file_support_version_hash_and_only_selected_feature(self):
  root=self.directory();installed(root);row=sdk_support(root)
  self.assertEqual(row['status'],'AVAILABLE');self.assertEqual(row['files']['emulator_features']['VirtioSndCard'],'on');self.assertEqual(len(row['files']['emulator_features']['sha256']),64)
  self.assertNotIn('DO_NOT_EXPORT',json.dumps(row));self.assertNotIn('Unrelated',json.dumps(row))
 def test_missing_duplicate_unknown_feature_and_wrong_sdk_stop(self):
  for content in ('Other=on\n','VirtioSndCard=on\nVirtioSndCard=off\n','VirtioSndCard=unknown_secret\n'):
   root=self.directory();installed(root);(root/'emulator/lib/advancedFeatures.ini').write_text(content);row=sdk_support(root);self.assertEqual(row['status'],'STOP');self.assertNotIn('unknown_secret',json.dumps(row))
  root=self.directory();self.assertEqual(sdk_support(root)['status'],'STOP');installed(root);(root/'emulator/source.properties').write_text('Pkg.Revision=37.4.0\nPkg.BuildId=16970787\n');self.assertEqual(sdk_support(root)['status'],'STOP')
 def test_exact_unique_soundhw_after_nul_parser_no_command_or_token_output(self):
  root=self.directory();path=root/'cmd';path.write_bytes(b'qemu-system-x86_64\0-grpc-token\0DO_NOT_EXPORT\0-soundhw\0hda\0')
  self.assertEqual(require_qemu_hda(nul_fields(path)),'hda');self.assertEqual(require_qemu_hda(iter(['qemu','-soundhw=hda'])),'hda')
  cases=[[],['-soundhw'],['-soundhw','virtio-snd-pci'],['-soundhw','unknown_secret'],['-soundhw','hda','-soundhw','hda'],['-soundhw=hda','-soundhw','hda'],['-soundhw','hda,input=off'],['-soundhw','hda','-device','virtio-snd-pci'],['-soundhw=hda','-device=virtio-snd-pci']]
  for args in cases:
   with self.subTest(args=args),self.assertRaises(HdaStop) as error:require_qemu_hda(iter(args))
   self.assertNotIn('unknown_secret',str(error.exception))
 def test_positive_guest_card_and_driver_must_correspond(self):
  self.assertEqual(guest_hda(guest()),dict(card_index=0,card_type='HDA_INTEL',driver='snd_hda_intel',root_uid=0))
  changes=[lambda r:r.update(root_uid=2000),lambda r:r['before'].update(status='UNAVAILABLE'),lambda r:r['before']['alsa'].update(fields=['0 [VirtIO]: VirtIO SoundCard']),lambda r:r['before']['alsa'].update(fields=['0 [Other]: Other Card']),lambda r:r['before']['alsa'].update(fields=[]),lambda r:r['before']['drivers'].update(fields=[dict(card='card1',driver_path='/sys/bus/pci/drivers/snd_hda_intel')]),lambda r:r['before']['drivers'].update(fields=[dict(card='card0',driver_path='/sys/bus/virtio/drivers/virtio_snd')]),lambda r:r['before']['drivers'].update(status='UNAVAILABLE')]
  for change in changes:
   row=guest();change(row)
   with self.assertRaises(HdaStop):guest_hda(row)
 def test_runtime_gate_no_prepare_before_support_and_owned_qemu(self):
  root=self.directory();calls=[]
  proof=types.SimpleNamespace(verify=lambda:calls.append('proof') or dict(audio={'42':dict(soundhw='hda')}))
  prepare=lambda meta:calls.append('native') or guest()
  row=runtime_gate(META,root,prepare,proof,root/'render');self.assertEqual(row['fixture'],'NOT_RUN');self.assertFalse(calls)
  installed(root);row=runtime_gate(META,root,prepare,proof,root/'render');self.assertEqual(row['status'],'AVAILABLE');self.assertEqual(calls,['proof','native'])
  calls.clear();proof.verify=lambda:(_ for _ in ()).throw(IsolationError('QEMU_EXECUTABLE'))
  self.assertEqual(runtime_gate(META,root,prepare,proof,root/'render')['fixture'],'NOT_RUN');self.assertFalse(calls)
 def test_guest_virtio_or_root_permission_failure_stops_not_fallback(self):
  root=self.directory();installed(root);proof=types.SimpleNamespace(verify=lambda:dict(audio={'42':dict(soundhw='hda')}))
  calls=[]
  for native in [dict(status='UNAVAILABLE',reason='ROOT_ID_NOT_ZERO'),dict(status='AVAILABLE',root_uid=0,before=dict(status='AVAILABLE',alsa=dict(status='AVAILABLE',fields=['0 [VirtIO]: VirtIO SoundCard']),drivers=dict(status='AVAILABLE',fields=[dict(card='card0',driver_path='/sys/bus/virtio/drivers/virtio_snd')])) )]:
   def prepare(meta):calls.append('once');return native
   result=runtime_gate(META,root,prepare,proof,root/'render');self.assertEqual(result['status'],'STOP');self.assertEqual(result['fixture'],'NOT_RUN')
  self.assertEqual(len(calls),2)
 def test_calibration_hard_stop_never_enters_original_fixture_arm(self):
  import pa_only_calibration as main
  root=self.directory();installed(root);previous=Path.cwd();os.chdir(root)
  try:
   Path('render').mkdir();proof=types.SimpleNamespace(verify=lambda:dict(audio={'42':dict(soundhw='hda')}));native=types.SimpleNamespace(prepare=lambda meta:dict(status='UNAVAILABLE'))
   with patch.dict(os.environ,dict(M06_SDK_INPUT_GATE='1',BUDDY_SYNTHETIC_AVD_PROBE='1',M06_NATIVE_READONLY='1',M06_REQUIRE_HDA='1',ANDROID_HOME=str(root))),patch.object(main,'preflight',return_value=META),patch('sdk_input_gate.PrivatePulse',return_value=proof),patch('native_readonly.NativeReadOnly',return_value=native),patch.object(main,'run_arm') as arm:
    self.assertEqual(main.main(),1);arm.assert_not_called()
   self.assertEqual(json.loads(Path('render/sdk-gate-calibration.json').read_text())['fixture'],'NOT_RUN')
  finally:os.chdir(previous)
 def test_require_hda_without_native_flag_cannot_bypass_runtime_gate(self):
  import pa_only_calibration as main
  root=self.directory();installed(root);previous=Path.cwd();os.chdir(root)
  try:
   Path('render').mkdir()
   for value in (None,'0'):
    with patch.dict(os.environ,dict(M06_SDK_INPUT_GATE='1',BUDDY_SYNTHETIC_AVD_PROBE='1',M06_REQUIRE_HDA='1',ANDROID_HOME=str(root))),patch.object(main,'preflight',return_value=META),patch.object(main,'run_arm') as arm:
     if value is None:os.environ.pop('M06_NATIVE_READONLY',None)
     else:os.environ['M06_NATIVE_READONLY']=value
     self.assertEqual(main.main(),1);arm.assert_not_called()
     self.assertEqual(json.loads(Path('render/sdk-gate-calibration.json').read_text())['fixture'],'NOT_RUN')
  finally:os.chdir(previous)
 def test_workflow_one_feature_override_no_avd_or_root_executed_here(self):
  text=Path('.github/workflows/v2-eyes.yml').read_text();launch=next(line for line in text.splitlines() if '-avd v2eyes -' in line)
  self.assertEqual(launch.count('-feature -VirtioSndCard'),1);self.assertNotIn('setprop',launch)
  self.assertLess(text.index('python3 scripts/m06/hda_guard.py'),text.index('-avd v2eyes'))
