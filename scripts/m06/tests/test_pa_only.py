import hashlib,json,math,os,subprocess,sys,tempfile,types,unittest,uuid,wave
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]))
from pa_only import PaOnlyMic,PaFailure,fixture,alignment
from pa_only_calibration import pa_transport_complete

class PaOnlyTests(unittest.TestCase):
 def setup_case(self,rate=16000):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);d=Path(temp.name);p=d/'x.wav'
  raw=b''.join(int(12000*math.sin(i*.073)+1500*math.sin(i*.031)).to_bytes(2,'little',signed=True) for i in range(rate//4))
  with wave.open(str(p),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(raw)
  meta=dict(name='fixture',nonce=str(uuid.uuid4()),sha256=hashlib.sha256(p.read_bytes()).hexdigest());events=[];state=[False]
  def write(v,**kw):state[0]=v.realAudioEnabled;events.append('true' if state[0] else 'false')
  def forbidden(*a,**kw):raise AssertionError('injectAudio forbidden')
  control=types.SimpleNamespace(stub=types.SimpleNamespace(setMicrophoneState=write,getMicrophoneState=lambda *a,**kw:types.SimpleNamespace(realAudioEnabled=state[0]),injectAudio=forbidden),pb=types.SimpleNamespace(MicrophoneState=lambda **kw:types.SimpleNamespace(**kw)),auth=(),Empty=lambda:None,close=lambda:None)
  proof=types.SimpleNamespace(verify=lambda:dict(source_output_present=True,qemu_source_outputs=[dict(corked=False)]))
  helper=PaOnlyMic(control=control,proof=proof,specs={'fixture':(p,meta['sha256'],rate)},directory=d)
  helper.before_restore=lambda:events.append('observer_stopped')
  class Monitor:
   process=types.SimpleNamespace(pid=2);end=10**12
   def finish(self):events.append('monitor_stopped');return bytes(rate*2*600//1000)+raw+bytes(rate*2*300//1000)
  class Player:
   pid=3;returncode=0
   def poll(self):return self.returncode
   def wait(self,**kw):events.append('playback_wait');return 0
   def terminate(self):events.append('playback_stopped');self.returncode=-15
   def kill(self):self.returncode=-9
  return helper,p,meta,raw,events,Monitor(),Player()
 def run_case(self,case,**overrides):
  h,p,m,raw,ev,mon,player=case
  with patch('pa_only.RequiredMonitor',return_value=mon) as monitor,patch('pa_only.subprocess.Popen',return_value=player) as play,patch('pa_only.binding',return_value=dict(target='validated')) as route,patch('pa_only.time.sleep'):
   for key,value in overrides.items():{'monitor':monitor,'play':play,'route':route}[key].side_effect=value
   result=h.play(p,m)
   self.assertEqual(play.call_count,1)
   return result
 def test_complete_16_and_24_preserve_body_and_stop_before_false(self):
  for rate in (16000,24000):
   case=self.setup_case(rate);row=self.run_case(case);h,p,m,raw,ev,*_=case
   self.assertEqual(row['source_samples'],rate//4);self.assertEqual(row['rate'],rate);self.assertGreater(row['alignment']['correlation'],.999)
   self.assertEqual(ev.count('true'),1);self.assertEqual(ev[-3:],['monitor_stopped','observer_stopped','false']);self.assertTrue(row['sdk_restored_false'])
   self.assertFalse(list(p.parent.glob('pa-payload-*')))
   with self.assertRaises(PaFailure):h.play(p,m)
 def test_missing_or_wrong_route_and_monitor_failure_hard_stop(self):
  for stage in ('monitor','route'):
   case=self.setup_case()
   with self.assertRaises(RuntimeError):self.run_case(case,**{stage:RuntimeError('PRIVATE_SENTINEL')})
   self.assertEqual(case[4][-1],'false');self.assertNotIn('PRIVATE_SENTINEL',next(case[1].parent.glob('mic-pa-*')).read_text())
 def test_bad_isolation_never_enables_or_plays(self):
  case=self.setup_case();case[0].proof.verify=lambda:(_ for _ in ()).throw(PaFailure('QEMU_INPUT_MISSING'))
  with self.assertRaises(PaFailure),patch('pa_only.subprocess.Popen') as play:
   case[0].play(case[1],case[2])
  play.assert_not_called();self.assertNotIn('true',case[4]);self.assertEqual(case[4][-1],'false')
 def test_corked_qemu_or_sdk_false_or_timeout_fail_and_reap(self):
  for fault in ('corked','false','timeout'):
   case=self.setup_case();h,p,m,raw,ev,mon,player=case
   if fault=='corked':h.proof.verify=lambda:dict(source_output_present=True,qemu_source_outputs=[dict(corked=True)])
   if fault=='false':h.state=lambda:False
   if fault=='timeout':
    def wait(**kw):
     if player.returncode is None:raise subprocess.TimeoutExpired('owned',1)
     return player.returncode
    player.returncode=None;player.wait=wait
   with self.assertRaises((PaFailure,subprocess.TimeoutExpired)):self.run_case(case)
   self.assertEqual(ev[-1],'false');self.assertIn('observer_stopped',ev)
 def test_restore_failure_visible_and_primary_error_preserved(self):
  case=self.setup_case();h=case[0];original=h.set
  def set_state(value):
   if not value:raise PaFailure('SDK_FALSE_NOT_OBSERVED')
   original(value)
  h.set=set_state
  with self.assertRaises(PaFailure):self.run_case(case)
  row=json.loads(next(case[1].parent.glob('mic-pa-*')).read_text());self.assertEqual(row['stage'],'RESTORE_FAILED');self.assertNotIn('sdk_restored_false',row)
 def test_primary_fault_survives_restore_fault(self):
  case=self.setup_case();h=case[0]
  h.proof.verify=lambda:(_ for _ in ()).throw(PaFailure('QEMU_INPUT_MISSING'))
  h.set=lambda value:(_ for _ in ()).throw(PaFailure('SDK_FALSE_NOT_OBSERVED'))
  with self.assertRaises(PaFailure) as raised:h.play(case[1],case[2])
  self.assertEqual(raised.exception.reason,'QEMU_INPUT_MISSING');self.assertTrue(raised.exception.__notes__)
 def test_fixture_hash_format_and_truncation_rejected(self):
  h,p,m,raw,*_=self.setup_case();bad=dict(m,sha256='0'*64)
  with self.assertRaises(PaFailure):fixture(p,bad,h.specs)
  with self.assertRaises(PaFailure):alignment(raw,raw[:100],16000)
  with self.assertRaises(PaFailure):fixture(p,m,{'fixture':(p,m['sha256'],24000)})
 def test_enter_receipt_requires_exact_derived_hash(self):
  from source_calibration import ENTER_SHA
  row=dict(nonce='x',name='enter',sha256=ENTER_SHA,backend='private Pulse paplay; no injectAudio',stage='COMPLETED',rate=16000,channels=1,sample_format='s16le',source_samples=64960,prefix_ms=600,prefix_samples=9600,tail_ms=300,payload_samples=79360,payload_sha256='6adff50b69642e42612c417e141e85ece88b4a03f765003cbe2fc363b0f1632a',playback_exit=0,sdk_true=True,sdk_restored_false=True,owned_stopped=True,transport_complete=True,alignment=dict(full_source_samples=64960,correlation=.999))
  self.assertTrue(pa_transport_complete(row,'x'))
  for key,value in [('payload_sha256','wrong'),('source_samples',79360),('sdk_restored_false',False),('owned_stopped',False)]:
   with self.subTest(key=key):self.assertFalse(pa_transport_complete(dict(row,**{key:value}),'x'))
 def test_binding_rejects_wrong_monitor_route_format_mute_and_pid(self):
  from pa_only import binding
  good=dict(index=1,client='4',source=1,sample_specification='s16le 1ch 24000Hz',mute=False,corked=False)
  for change in ({},{'source':0},{'sample_specification':'s16le 1ch 16000Hz'},{'mute':True},{'client':'9'}):
   def query(kind):
    return {'clients':[dict(index=4,properties={'application.process.id':'77'})],'source-outputs':[dict(good,**change)],'sources':[dict(index=0,name='v2_playback.monitor'),dict(index=1,name='m06_input.monitor')]}[kind]
   proof=types.SimpleNamespace(pactl=query)
   if not change:self.assertEqual(binding(proof,77,'source-outputs',24000)['target'],'m06_input.monitor')
   else:
    with self.assertRaises(PaFailure):binding(proof,77,'source-outputs',24000)
