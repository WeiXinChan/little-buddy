import copy,json,os,shlex,subprocess,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
from native_readonly import *

OBJ='/vendor/lib64/hw/android.hardware.audio.legacy@7.1-impl.ranchu.so'
TINY='/vendor/lib64/libtinyalsa.so'
META=dict(identity_ok=True,known_stub=False,properties={'ro.build.fingerprint':dict(value=FINGERPRINT)})

class FakeADB:
 def __init__(self):self.calls=[];self.uid=0;self.replaced=False;self.missing=False;self.deny=None;self.truncate=None;self.logs_fail=False
 def __call__(self,args,limit=131072,seconds=3):
  self.calls.append((args,limit,seconds));command=args[-1];text='';code=0
  if args[-1] in ('root','wait-for-device'):text=''
  elif command=='id -u':text=str(self.uid)+'\n'
  elif command==PS_COMMAND:text='PID UID NAME\n447 1041 android.hardware.audio.service\n999 1000 unrelated\n'
  elif '/stat;' in command:text=f'447 {200 if self.replaced else 100}\n1041\n{EXE}\n'
  elif '/maps' in command:text='' if self.missing else OBJ+'\n'+TINY+'\n'
  elif command.startswith('sha256sum '):text='a'*64+'  '+command[10:]+'\n'
  elif 'Build ID:' in command:text='aabbccddeeff00112233\n'
  elif command=='date +%s':text='1770000000\n'
  elif command==ALSA_COMMAND:text='ALSA_PATH /proc/asound/cards\n0 [Intel]: HDA-Intel\nALSA_PATH /proc/asound/card0/pcm0c/sub0/status\nstate: RUNNING\nhw_ptr: 200\nowner_pid: 447\nrate: 16000\n'
  elif command=='ls -ln /dev/snd':text='crw-rw---- 1 1041 1005 116, 0 2026-11-25 00:00 controlC0\n'
  elif command==DRIVERS:text='card0 /sys/bus/pci/drivers/snd_hda_intel\n'
  elif command=='command -v tinymix':text='/vendor/bin/tinymix\n'
  elif command=='/vendor/bin/tinymix':text='0 BOOL 2 Mic Capture Switch  On On\n1 INT 2 Capture Volume  87 87\n2 ENUM 1 Input Source  Internal Mic\n'
  elif 'logcat -d' in command:
   text='1770000000.000 LATE_SILENCE silence_us=1000\n'
   if self.logs_fail:code=7
  else:raise AssertionError('unexpected command')
  if self.deny is not None and self.deny in command:code=1;text='SENSITIVE_PERMISSION_BODY'
  capped=self.truncate is not None and self.truncate in command
  return text.encode(),dict(status='AVAILABLE' if code==0 else 'UNAVAILABLE',exit_code=code,eof=True,capped=capped)

class NativeReadOnlyTests(unittest.TestCase):
 def setup_probe(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.addCleanup(patch.stopall)
  patch.dict(os.environ,{'M06_NATIVE_READONLY':'1'}).start()
  fake=FakeADB();proof=types.SimpleNamespace(verify=lambda:dict(owned=True));return NativeReadOnly(Path(tmp.name),fake,proof),fake
 def test_full_prepare_and_during_queries_root_once_and_typed_evidence(self):
  probe,fake=self.setup_probe();row=probe.prepare(META)
  self.assertEqual(row['status'],'AVAILABLE');self.assertEqual(row['root_uid'],0);self.assertEqual(row['objects'][0]['path'],OBJ)
  self.assertEqual(row['before']['mixer']['fields'][0]['values'],[True,True]);self.assertEqual(row['before']['logs']['fields']['counts']['LATE_SILENCE'],1)
  self.assertEqual(probe.prepare(META)['reason'],'ROOT_ALREADY_ATTEMPTED');self.assertEqual(sum(c[0][-1]=='root' for c in fake.calls),1)
  self.assertEqual(probe.snapshot('during')['status'],'AVAILABLE')
  self.assertTrue(all(c[0][:3]==ADB for c in fake.calls));self.assertTrue(any(c[0][-1].startswith('set -o pipefail; logcat') for c in fake.calls))
  self.assertNotIn('SENSITIVE_PERMISSION_BODY',json.dumps(row))
 def test_wrong_identity_and_denied_root_do_not_retry(self):
  probe,fake=self.setup_probe();self.assertEqual(probe.prepare(dict(META,identity_ok=False))['status'],'UNAVAILABLE');self.assertFalse(fake.calls)
  probe,fake=self.setup_probe();fake.uid=2000
  self.assertEqual(probe.prepare(META)['reason'],'ROOT_ID_NOT_ZERO');probe.prepare(META);self.assertEqual(sum(c[0][-1]=='root' for c in fake.calls),1)
 def test_pid_replaced_and_object_set_changed_do_not_reattach(self):
  probe,fake=self.setup_probe();probe.prepare(META);fake.replaced=True;self.assertEqual(probe.snapshot('during')['reason'],'PID_REPLACED')
  self.assertEqual(sum(c[0][-1]==PS_COMMAND for c in fake.calls),1)
  probe,fake=self.setup_probe();probe.prepare(META);fake.missing=True;self.assertEqual(probe.snapshot('during')['reason'],'OBJECT_SET_CHANGED')
 def test_missing_object_or_optional_tool_stays_honest_preserves_other_sections(self):
  probe,fake=self.setup_probe();fake.missing=True;fake.deny='command -v tinymix';row=probe.prepare(META)
  self.assertEqual(row['objects']['status'],'UNAVAILABLE');self.assertEqual(row['before']['mixer']['status'],'UNAVAILABLE');self.assertTrue(row['before']['alsa']['fields'])
 def test_permission_timeout_truncation_invalid_utf8_never_parse_as_zero_errors(self):
  probe,fake=self.setup_probe();probe.prepare(META);fake.logs_fail=True
  self.assertEqual(probe.snapshot('during')['logs']['status'],'UNAVAILABLE')
  fake.logs_fail=False;fake.truncate='logcat';self.assertEqual(probe.snapshot('during')['logs']['status'],'UNAVAILABLE')
  for result in [(b'1770000000 PCM_READ_FAILED',dict(status='UNAVAILABLE',eof=False,exit_code=-15,capped=False)),(b'\xff',dict(status='AVAILABLE',eof=True,exit_code=0,capped=False))]:
   probe.run=lambda *a,**kw:result
   with self.assertRaises(Unavailable):probe.query('date +%s')
 def test_actual_awk_whitelist_includes_legacy_and_excludes_arbitrary_maps(self):
  program=shlex.split(MAPS_AWK)[1]
  lines=''.join('100-200 r-xp 0 00:00 123 '+p+'\n' for p in (OBJ,TINY,'/vendor/lib64/libsecret.so','/data/local/tmp/evil.so'))
  out=subprocess.check_output(['awk',program],input=lines,text=True)
  self.assertEqual(allowed_objects(out),[OBJ,TINY])
  program=shlex.split(PS_COMMAND)[-1]
  projection=subprocess.check_output(['awk',program],input='PID UID NAME\n447 1041 android.hardware.audio.service\n999 1000 unrelated_secret\n',text=True)
  self.assertEqual(process_list(projection)['pid'],447);self.assertNotIn('secret',projection)
  with self.assertRaises(Unavailable):allowed_objects('/vendor/lib64/libsecret.so')
 def test_log_producer_failure_pipefail_and_sanitised_enum_only(self):
  code=subprocess.run(['bash','-c',"set -o pipefail; (exit 7) | awk '{print}'"],stdout=subprocess.PIPE).returncode;self.assertEqual(code,7)
  row=log_enums('1770000000.1 PCM_READ_FAILED (-22) body_secret\n1770000000.2 UNKNOWN token_secret\n1769999999 PCM_OPEN_FAILED\n',1770000000,1770000001)
  self.assertEqual(row['counts']['PCM_READ_FAILED'],1);self.assertEqual(row['events'][0]['numbers']['error_code'],-22);self.assertNotIn('secret',json.dumps(row))
 def test_unknown_mixer_fields_never_escape(self):
  out=mixer('0 BOOL 2 Mic Capture Switch  On Off\n1 ENUM 1 Input Source  SECRET_VALUE\n2 INT 1 Mic Token  100\n')
  self.assertEqual(out[0]['values'],[True,False]);self.assertIsNone(out[1]['values']);self.assertNotIn('SECRET_VALUE',json.dumps(out));self.assertEqual(len(out),2)
 def test_guest_awk_log_projection_full_pipeline_drops_bodies_and_unknown(self):
  start=1770000000;end=start+1
  args=shlex.split(LOG_AWK.replace('START',str(start)).replace('END',str(end)))
  raw='1770000000.100 447 447 E tag: pcm_open failed for nChannels=1 sampleRateHz=16000 private_secret\n1770000000.200 447 447 W tag: pcm_readi failed with arbitrary_secret (-22)\n1770000000.300 447 447 D tag: TinyalsaSource::read pcm_readi was late delivering frames, inserting 320 us of silence\n1770000000.400 447 447 E tag: unrelated private_secret\n'
  projected=subprocess.check_output(args,input=raw,text=True)
  self.assertNotIn('secret',projected);result=log_enums(projected,start,end)
  self.assertEqual(result['counts']['PCM_OPEN_FAILED'],1);self.assertEqual(result['counts']['PCM_READ_FAILED'],1);self.assertEqual(result['counts']['LATE_SILENCE'],1)
  self.assertEqual(result['events'][0]['numbers']['sampleRateHz'],16000)
 def test_snapshot_budget_stops_commands_and_maps_permission_not_false_set_change(self):
  probe,fake=self.setup_probe();probe.prepare(META);before=len(fake.calls)
  with patch('native_readonly.time.monotonic',side_effect=[0,9]):row=probe.snapshot('during')
  self.assertEqual(row['reason'],'SNAPSHOT_BUDGET');self.assertEqual(len(fake.calls),before)
  fake.deny='/maps';row=probe.snapshot('during')
  self.assertEqual(row['object_status'],'UNAVAILABLE');self.assertEqual(row['object_reason'],'COMMAND_UNAVAILABLE_OR_TRUNCATED');self.assertEqual(row['status'],'AVAILABLE')
 def test_mid_snapshot_pid_change_invalidates_phase_not_reattach(self):
  probe,fake=self.setup_probe();probe.prepare(META);original=fake.__call__;guards=[0]
  def run(args,**kw):
   if '/stat;' in args[-1]:
    guards[0]+=1
    if guards[0]>1:fake.replaced=True
   return original(args,**kw)
  probe.run=run;self.assertEqual(probe.snapshot('during')['reason'],'PID_REPLACED')
 def test_single_tab_tinymix_columns_keep_known_values_drop_unknown(self):
  rows=mixer('0\tINT\t2\tCapture Volume\t87 87\n1\tBOOL\t2\tMic Capture Switch\tOn Off\n2\tENUM\t1\tInput Source\tSECRET_VALUE\n')
  self.assertEqual(rows[0]['name'],'Capture Volume');self.assertEqual(rows[0]['values'],[87,87]);self.assertEqual(rows[1]['values'],[True,False]);self.assertIsNone(rows[2]['values']);self.assertNotIn('SECRET_VALUE',json.dumps(rows))
 def test_parent_workflow_serial_reaches_actual_private_pulse_init_before_root(self):
  probe,fake=self.setup_probe();text=Path('.github/workflows/v2-eyes.yml').read_text();line=next(x.strip() for x in text.splitlines() if x.strip().startswith('export ANDROID_SERIAL='))
  serial=subprocess.check_output(['bash','-c',line+'; printf "%s" "$ANDROID_SERIAL"'],text=True)
  root=probe.directory;(root/'v2-avd').mkdir(mode=0o700);(root/'v2-runtime').mkdir(mode=0o700)
  env=dict(GITHUB_ACTIONS='true',RUNNER_ENVIRONMENT='github-hosted',BUDDY_SYNTHETIC_AVD_PROBE='1',M06_SDK_INPUT_GATE='1',ANDROID_SERIAL=serial,RUNNER_TEMP=str(root),M06_EMULATOR_PID=str(os.getpid()),M06_PULSE_PID=str(os.getpid()),PULSE_SERVER='unix:'+str(root/'v2-avd/pulse.sock'))
  probe.proof=None
  with patch.dict(os.environ,env),patch.object(PrivatePulse,'verify',return_value=dict(owned=True)) as verified:
   os.environ.pop('ANDROID_SERIAL')
   negative=NativeReadOnly(root,fake);self.assertEqual(negative.prepare(META)['root_attempts'],0);self.assertFalse(fake.calls);verified.assert_not_called()
   os.environ['ANDROID_SERIAL']=serial
   self.assertEqual(probe.prepare(META)['root_attempts'],1);verified.assert_called_once()
 def test_explicit_base_view_can_collect_native_but_does_not_grant_fixture(self):
  from sdk_input_gate import MetadataPulseView
  probe,fake=self.setup_probe();probe.proof=types.SimpleNamespace(verify=lambda:(_ for _ in ()).throw(AssertionError('strict host representation must not block metadata')))
  pulse=types.SimpleNamespace(verify_metadata_only=lambda:dict(proof_scope='BASE_METADATA_ONLY'))
  row=probe.prepare(META,metadata_proof=MetadataPulseView(pulse));self.assertEqual(row['status'],'AVAILABLE');self.assertEqual(row['private_proof_scope'],'BASE_METADATA_ONLY');self.assertNotIn('fixture_authorization',row);self.assertEqual(sum(c[0][-1]=='root' for c in fake.calls),1)
 def test_resume_and_during_full_path_never_root_again_and_reject_stale_pid(self):
  probe,fake=self.setup_probe();probe.prepare(META);resumed=NativeReadOnly(probe.directory,fake)
  resumed.resume();self.assertEqual(resumed.snapshot('during')['status'],'AVAILABLE')
  nonce='12345678-1234-1234-1234-123456789abc'
  with patch('native_readonly.NativeReadOnly',return_value=resumed):row=during(probe.directory,nonce,dict(native_session=97,session=97,actual=7,requested=7))
  self.assertEqual(row['source_evidence']['native_session'],97);self.assertIn('fixture-request',row['source_evidence_scope']);self.assertEqual(sum(c[0][-1]=='root' for c in fake.calls),1)
  fake.replaced=True
  with self.assertRaises(Unavailable):NativeReadOnly(probe.directory,fake).resume()
 def test_active_wiring_finalises_pa_window_and_does_not_claim_late_read_during(self):
  import native_input_metadata as metadata
  import threading
  with tempfile.TemporaryDirectory() as d:
   directory=Path(d);nonce='12345678-1234-1234-1234-123456789abc';done=threading.Event();done.set();started=threading.Event();started.set()
   clock=iter([10,20]);window=PlaybackWindow(clock=lambda:next(clock));window.begin();window.finish()
   native=dict(nonce=nonce,status='AVAILABLE',host_monotonic_ns=30,ended_monotonic_ns=40,source_evidence=dict(native_session=97),alsa=dict(started_monotonic_ns=31,ended_monotonic_ns=39))
   with patch.object(metadata,'query',return_value=dict(status='AVAILABLE',input_threads=[],started_monotonic_ns=1,ended_monotonic_ns=2)),patch('native_readonly.during',return_value=native):
    metadata.active(directory,nonce,done,transport_backend='pa-only',native_started=started,source_evidence=dict(native_session=97),playback_window=window)
   row=json.loads((directory/('active-'+nonce+'.json')).read_text());self.assertEqual(row['native_readonly']['snapshot_overlap']['status'],'NONE');self.assertTrue(row['playback_completion_observed']);self.assertNotIn('rpc_completion_observed',row)
 def test_parent_prepare_precedes_arm_and_does_not_touch_original_pa_parameters(self):
  import pa_only_calibration as main
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);previous=Path.cwd();os.chdir(tmp.name)
  try:
   Path('render').mkdir();events=[]
   proof=types.SimpleNamespace(prepare=lambda meta:events.append('prepare'))
   result=dict(test_exit=1,transport_complete=True,alignment_exit=0,finished=True,released=True,stopped=True,worker_done=True,lease_available=True,recording=False)
   def arm(source,validator,**kwargs):
    events.append('arm');self.assertEqual(source,7);self.assertEqual(kwargs,dict(input_backend='pa-only',receipt_prefix='mic-pa-'));return result
   with patch.dict(os.environ,dict(M06_REQUIRE_HDA='0',M06_NATIVE_READONLY='1',M06_SDK_INPUT_GATE='1',BUDDY_SYNTHETIC_AVD_PROBE='1')),patch.object(main,'preflight',return_value=META),patch('native_readonly.NativeReadOnly',return_value=proof),patch.object(main,'run_arm',side_effect=arm):
    self.assertEqual(main.main(),1)
   self.assertEqual(events,['prepare','arm'])
  finally:os.chdir(previous)
 def test_incomplete_bound_metadata_cannot_be_available(self):
  probe,fake=self.setup_probe();probe.run=lambda *a,**k:(b'0',dict(status='AVAILABLE'))
  with self.assertRaises(Unavailable):probe.query('id -u')
 def test_flinger_only_live_input_typed_track_and_no_defaults(self):
  text='Input thread 0x123, name AudioIn_36, tid 3196, type 3 (RECORD):\n I/O handle: 54\n Sample rate: 16000 Hz\n HAL format: 0x1 (AUDIO_FORMAT_PCM_16_BIT)\n Audio source: 7 (AUDIO_SOURCE_VOICE_COMMUNICATION)\n Active Id Client(pid/uid) Session Port Id\n yes 1 1427/10441 97 88 other_private_body\n 0 Effect Chains\nHistorical Thread Log\n- Sample rate: 48000 Hz\n'
  row=flinger_fields(text)[0];self.assertEqual(row['tracks'][0]['session'],97);self.assertEqual(row['io_handle'],54);self.assertEqual(row['gain_status'],'UNAVAILABLE');self.assertNotIn('private',json.dumps(row))

class TimingTests(unittest.TestCase):
 def test_sections_before_partial_full_after_and_unsealed(self):
  window=dict(started_monotonic_ns=100,ended_monotonic_ns=200)
  for start,end,expect in [(10,50,'NONE'),(50,150,'PARTIAL'),(110,150,'FULL'),(150,250,'PARTIAL'),(210,250,'NONE')]:
   self.assertEqual(overlap(dict(started_monotonic_ns=start,ended_monotonic_ns=end),window)['status'],expect)
  self.assertEqual(overlap({},window)['status'],'UNKNOWN')
 def test_window_no_renewal_and_late_snapshot_not_during(self):
  clock=iter([100,200]);window=PlaybackWindow(clock=lambda:next(clock));window.begin();window.begin();window.finish();window.finish()
  with tempfile.TemporaryDirectory() as d:
   row=dict(source_evidence=dict(native_session=97),host_monotonic_ns=210,ended_monotonic_ns=400,alsa=dict(started_monotonic_ns=220,ended_monotonic_ns=300))
   result=finalise_during(Path(d),'abc',row,window,dict(input_threads=[dict(name='AudioIn_other',tracks=[dict(session=113)])]))
   self.assertEqual(result['snapshot_overlap']['status'],'NONE');self.assertEqual(result['alsa']['pa_read_overlap']['status'],'NONE');self.assertEqual(result['flinger_session_match']['status'],'UNAVAILABLE')
 def test_source_request_session_only_matches_live_track(self):
  clock=iter([100,200]);window=PlaybackWindow(clock=lambda:next(clock));window.begin();window.finish()
  with tempfile.TemporaryDirectory() as d:
   row=dict(source_evidence=dict(native_session=97),host_monotonic_ns=110,ended_monotonic_ns=180)
   result=finalise_during(Path(d),'abc',row,window,dict(started_monotonic_ns=10,ended_monotonic_ns=50,input_threads=[dict(name='AudioIn_36',io_handle=54,tracks=[dict(session=97,active=True)])]))
   self.assertEqual(result['snapshot_overlap']['status'],'FULL');self.assertEqual(result['flinger_read_overlap']['status'],'NONE');self.assertEqual(result['flinger_session_match']['matches'][0]['session'],97)

 def test_same_session_inactive_track_is_not_available_association(self):
  window=PlaybackWindow(clock=lambda:100);window.begin();window.finish()
  with tempfile.TemporaryDirectory() as d:
   row=dict(source_evidence=dict(native_session=97),host_monotonic_ns=100,ended_monotonic_ns=100)
   result=finalise_during(Path(d),'abc',row,window,dict(input_threads=[dict(name='AudioIn_36',io_handle=54,tracks=[dict(session=97,active=False)])]))
   self.assertEqual(result['flinger_session_match']['status'],'UNAVAILABLE');self.assertEqual(result['flinger_session_match']['matches'],[])
