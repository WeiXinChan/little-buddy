"""Synthetic Pulse source -> AVD microphone. No replacement of Android AudioRecord."""
import subprocess,json,hashlib,re,sys,os,threading
from native_input_metadata import active
from route_evidence import play_fixture
from fixture_timing import FixtureTiming
from pathlib import Path
root=Path('app/src/androidTest/assets/m06-commands')
allowed={r['name']:r['sha256'] for r in json.loads((root/'cases.json').read_text())['cases']}
allowed.update({r['name']:r['sha256'] for r in json.loads((root/'provenance.json').read_text())['rows']})
paths={name:root/(name+'.wav') for name in allowed}
protocol=Path('app/src/androidTest/assets/m06-protocol-v2')
for row in json.loads((protocol/'provenance.json').read_text()):
 name='v2_'+row['name'];allowed[name]=row['sha256'];paths[name]=protocol/(row['name']+'.wav')
short=json.loads((protocol/'derived-confirm.json').read_text());allowed[short['name']]=short['sha256'];paths[short['name']]=protocol/'confirm_exit_short.wav'
production=Path('app/src/main/assets/management')
for row in json.loads((production/'provenance.json').read_text())['rows']:
 name='prod_'+row['name'];allowed[name]=row['sha256'];paths[name]=production/(row['name']+'.wav')
virtual_mic=None
if os.environ.get('M06_AUDIO_INPUT')=='grpc':
 from grpc_mic import GrpcMic
 try:virtual_mic=GrpcMic()
 except Exception as e:
  Path('render/grpc-mic-init-failure.json').write_text(json.dumps(dict(stage='authenticated_loopback_setup',error=type(e).__name__)))
  raise RuntimeError('virtual mic setup '+type(e).__name__) from None
if os.environ.get('M06_AUDIO_INPUT')=='pa-only':
 from pa_only import PaOnlyMic
 virtual_mic=PaOnlyMic()
calibration=os.environ.get('M06_CALIBRATION_SOURCE');calibration_nonce=os.environ.get('M06_CALIBRATION_NONCE')
extra=[]
if calibration is not None:
 assert os.environ.get('BUDDY_SYNTHETIC_AVD_PROBE')=='1' and calibration in ('7','6') and re.fullmatch(r'[a-f0-9-]{36}',calibration_nonce or '')
 extra=['-e','m06_source',calibration,'-e','m06_nonce',calibration_nonce]
metadata_worker=None
rpc_done=threading.Event()
p=subprocess.Popen(['adb','shell','am','instrument','-w','-r','-e','class','com.littlebuddy.V2MicrophoneCommandTest']+extra+['com.littlebuddy.sim.v2.test/com.littlebuddy.SimUiRunner'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
output=[]
timing=None
try:
 for line in p.stdout:
  print(line,end='',flush=True);output.append(line)
  if line.startswith('INSTRUMENTATION_STATUS: m06_request='):
   q=json.loads(line.strip().split('=',1)[1]);name=q['name'];nonce=q['nonce'];private=q['root'];pkg=q['package']
   if pkg!='com.littlebuddy.sim.v2' or q['user']!=0:raise ValueError('target user/package')
   if name not in allowed or not re.fullmatch(r'[a-z0-9_.]+',name) or not re.fullmatch(r'[a-f0-9-]{36}',nonce):raise ValueError('fixture/nonce allowlist')
   if not re.fullmatch(r'/[A-Za-z0-9_./]+',private) or not private.endswith('/'+pkg+'/files'):raise ValueError('private root')
   if name=='enter' and calibration is not None:
    assert nonce==calibration_nonce and q['source_configuration']['nonce']==nonce and q['source_configuration']['requested']==int(calibration) and q['source_configuration']['actual']==int(calibration) and q['source_configuration']['session']==q['source_configuration']['native_session'] and q['source_configuration']['recording'] and q['source_configuration']['frames']>0
    native_started=threading.Event() if os.environ.get('M06_NATIVE_READONLY')=='1' else None
    playback_window=None
    if native_started is not None:
     from native_readonly import PlaybackWindow
     playback_window=PlaybackWindow()
    metadata_worker=threading.Thread(target=active,args=(Path('render/native-input'),nonce,rpc_done),kwargs=dict(transport_backend=os.environ.get('M06_AUDIO_INPUT','grpc'),native_started=native_started,source_evidence=q.get('source_configuration'),playback_window=playback_window), name='owned-native-metadata');metadata_worker.start()
    if os.environ.get('M06_AUDIO_INPUT')=='pa-only':
     def stop_metadata():
      rpc_done.set();metadata_worker.join(18)
      if metadata_worker.is_alive():raise RuntimeError('owned metadata observer alive')
     virtual_mic.before_restore=stop_metadata
     if native_started is not None:
      def pa_started():playback_window.begin();native_started.set()
      virtual_mic.during_playback=pa_started;virtual_mic.playback_finished=playback_window.finish
   timing=FixtureTiming(q) if name=='enter' and virtual_mic and os.environ.get('BUDDY_SYNTHETIC_AVD_PROBE')=='1' else None
   if timing:timing.step('PWD_START')
   pwd=subprocess.check_output(['adb','shell','run-as',pkg,'pwd'],text=True,timeout=5).strip()
   if timing:timing.step('PWD_DONE_READLINK_START')
   canonical=subprocess.check_output(['adb','shell','run-as',pkg,'readlink','-f',private],text=True,timeout=5).strip()
   if timing:timing.step('READLINK_DONE_DIRECTORY_TEST_START')
   subprocess.run(['adb','shell','run-as',pkg,'test','-d',private],check=True,timeout=5)
   if timing:timing.step('DIRECTORY_TEST_DONE')
   if canonical!=private:raise ValueError('private root mismatch')
   print(json.dumps(dict(event='handshake_ready',nonce=nonce,root=private,run_as_pwd=pwd)),flush=True)
   path=paths[name]
   if hashlib.sha256(path.read_bytes()).hexdigest()!=allowed[name] or q['sha256']!=allowed[name]:raise ValueError('fixture hash')
   if timing:timing.step('FIXTURE_HASH_VERIFIED')
   fixture_metadata=dict(nonce=nonce,name=name,sha256=allowed[name])
   diagnostic=virtual_mic.play(path,fixture_metadata,timing=timing) if virtual_mic else play_fixture(path,fixture_metadata,monitor=(name=="enter" and os.environ.get("BUDDY_SYNTHETIC_AVD_PROBE")=="1"))
   if metadata_worker:rpc_done.set()
   print(json.dumps(diagnostic),flush=True)
   if timing:timing.step('PLAY_RETURNED')
   reply=json.dumps(dict(nonce=nonce,name=name,sha256=allowed[name],state='completed',playback_exit=0))
   subprocess.run(['adb','shell','run-as',pkg,'tee',private+'/m06-'+nonce+'.json'],input=reply,text=True,stdout=subprocess.PIPE,check=True,timeout=5)
   if timing:timing.step('COMPLETION_FILE_WRITTEN')
 result=p.wait(timeout=30)
 if result or not any('OK (1 test)' in x for x in output):sys.exit(1)
except Exception as error:
 if timing:timing.step('CONTROLLER_FAILED',error_class=type(error).__name__)
 # Let the bounded instrumentation await write real timeline/proof before cleanup.
 try:p.wait(timeout=40)
 except subprocess.TimeoutExpired:pass
 raise
finally:
 cleanup_failed=False
 rpc_done.set()
 if metadata_worker:
  metadata_worker.join(18)
  cleanup_failed=metadata_worker.is_alive()
 try:
  if virtual_mic:virtual_mic.close()
 finally:
  if p.poll() is None:p.terminate();p.wait(timeout=10)
 if cleanup_failed:
  active_error=sys.exception()
  if active_error:active_error.add_note('owned metadata worker failed to retire')
  else:raise RuntimeError('owned metadata worker failed to retire')
