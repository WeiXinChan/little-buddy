import json,os,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import metadata_only_observation as m
from hda_guard import audio_hda_projection
BASE=dict(proof_scope='BASE_METADATA_ONLY',audio={'42':dict(hda_projection=audio_hda_projection(['-feature','-VirtioSndCard']))})
class MetadataEntryTests(unittest.TestCase):
 def setup(self):
  calls=[];state=[False]
  def set_state(msg,**kw):calls.append(('sdk',msg.realAudioEnabled));state[0]=msg.realAudioEnabled
  def get_state(*a,**kw):return types.SimpleNamespace(realAudioEnabled=state[0])
  control=types.SimpleNamespace(stub=types.SimpleNamespace(setMicrophoneState=set_state,getMicrophoneState=get_state),pb=types.SimpleNamespace(MicrophoneState=lambda **kw:types.SimpleNamespace(**kw)),Empty=lambda:None,auth=(),close=lambda:calls.append(('close',)))
  proof=types.SimpleNamespace(verify_metadata_only=lambda:BASE)
  def prepare(meta,metadata_proof):
   self.assertEqual(metadata_proof.verify()['proof_scope'],'BASE_METADATA_ONLY');calls.append(('root_once',));return dict(status='AVAILABLE',root_uid=0,root_attempts=1)
  native=types.SimpleNamespace(prepare=prepare,enumeration_metadata=lambda **kw:dict(mode='METADATA_ONLY',identity_rechecked=True,fixture_authorization=False))
  return calls,control,proof,native
 def execute(self,d,c,n,p):
  def run(args,**kw):
   value=m.PROPERTIES.get(args[-1],'')
   return value.encode(),dict(status='AVAILABLE',exit_code=0,eof=True,capped=False)
  with patch.dict(os.environ,dict(M06_METADATA_ONLY='1',M06_NATIVE_READONLY='1',ANDROID_HOME='/synthetic')):
   return m.observe(Path(d),run=run,proof_factory=lambda:p,native_factory=lambda **kw:n,control_factory=lambda:c,support=lambda _:dict(status='AVAILABLE'))
 def test_entry_metadata_only_once_prepare_never_enables_and_final_false(self):
  calls,c,p,n=self.setup()
  with tempfile.TemporaryDirectory() as d:
   self.assertEqual(self.execute(d,c,n,p),0);row=json.loads((Path(d)/'result.json').read_text())
  self.assertEqual(calls,[('sdk',False),('root_once',),('sdk',False),('close',)])
  self.assertEqual(row['status'],'OBSERVED_NOT_PRODUCT_PASS');self.assertFalse(row['fixture_authorization']);self.assertEqual(row['fixture'],'NOT_RUN')
 def test_prepare_failure_does_not_retry_or_enumerate_restores_false(self):
  calls,c,p,n=self.setup();n.prepare=Mock(return_value=dict(status='UNAVAILABLE',root_attempts=1));n.enumeration_metadata=Mock()
  with tempfile.TemporaryDirectory() as d:self.assertEqual(self.execute(d,c,n,p),1)
  n.prepare.assert_called_once();n.enumeration_metadata.assert_not_called();self.assertEqual(calls[-2:],[('sdk',False),('close',)])
 def test_isolation_or_host_mode_failure_never_opens_control_or_root(self):
  calls,c,p,n=self.setup();n.prepare=Mock()
  for base in ({'proof_scope':'FULL_AUDIO_ISOLATION'},dict(BASE,audio={'42':dict(hda_projection=audio_hda_projection([]))})):
   p.verify_metadata_only=lambda:base
   with tempfile.TemporaryDirectory() as d:
    self.assertEqual(self.execute(d,c,n,p),1)
   self.assertEqual(calls,[]);n.prepare.assert_not_called()
 def test_final_false_read_failure_is_stop_not_success(self):
  calls,c,p,n=self.setup();reads=[False,True]
  c.stub.getMicrophoneState=lambda *a,**kw:types.SimpleNamespace(realAudioEnabled=reads.pop(0))
  with tempfile.TemporaryDirectory() as d:
   self.assertEqual(self.execute(d,c,n,p),1);row=json.loads((Path(d)/'result.json').read_text())
  self.assertFalse(row['sdk_final_false']);self.assertEqual(row['status'],'STOP')
 def test_unknown_metadata_does_not_become_fixture_permission(self):
  calls,c,p,n=self.setup();n.enumeration_metadata=lambda **kw:dict(identity_rechecked=False,status='UNAVAILABLE')
  with tempfile.TemporaryDirectory() as d:
   self.assertEqual(self.execute(d,c,n,p),1);row=json.loads((Path(d)/'result.json').read_text())
  self.assertEqual(row['fixture'],'NOT_RUN');self.assertFalse(row['fixture_authorization'])

 def test_one_publication_gate_rejects_unrelated_push_rerun_missing_or_wrong_transition(self):
  import copy
  after='a'*40
  event=dict(action='synchronize',number=36,before=m.PUBLICATION_BEFORE,after=after,pull_request=dict(number=36,head=dict(ref='agent/agent/70f7ce4d7235',sha=after,repo=dict(full_name='WeiXinChan/little-buddy'))))
  self.assertEqual(m.publication_gate(event,'1','WeiXinChan/little-buddy',after,m.PUBLICATION_BEFORE)['status'],'ONE_PUBLICATION_ALLOWED')
  for change in (lambda e:e.pop('before'),lambda e:e.update(before='b'*40),lambda e:e.pop('after'),lambda e:e.update(after='c'*40),lambda e:e.update(action='reopened'),lambda e:e['pull_request']['head'].update(ref='main')):
   invalid=copy.deepcopy(event);change(invalid)
   with self.assertRaises(m.Stop):m.publication_gate(invalid,'1','WeiXinChan/little-buddy',after,m.PUBLICATION_BEFORE)
  for attempt in ('2','0','',None):
   with self.assertRaises(m.Stop):m.publication_gate(event,attempt,'WeiXinChan/little-buddy',after,m.PUBLICATION_BEFORE)
  with self.assertRaises(m.Stop):m.publication_gate(event,'1','WeiXinChan/little-buddy',after,'b'*40)
