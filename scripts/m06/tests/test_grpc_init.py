"""Initialization fault injection only; fake services never prove emulator authentication."""
import importlib.util,unittest,tempfile,json,os,sys,types,hashlib
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('grpc_mic_init',Path(__file__).parents[1]/'grpc_mic.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class RpcError(Exception):
 def __init__(self,code):super().__init__('DO_NOT_EXPORT_RPC_BODY');self.value=code
 def code(self):return types.SimpleNamespace(name=self.value)
class Channel:
 def close(self):pass
class InitTests(unittest.TestCase):
 def fixture(self,variant):
  secret='SECRET_DESCRIPTOR_TOKEN_SENTINEL'
  with tempfile.TemporaryDirectory() as temp:
   base=Path(temp);root=base/'v2-runtime';root.mkdir(mode=0o700);(root/'avd/running').mkdir(parents=True)
   if variant=='mode':root.chmod(0o755)
   pid=os.getpid();(root/'avd/running'/f'pid_{pid}.ini').write_text(f'port.serial=5554\ngrpc.port=8554\ngrpc.token={secret}\n')
   sdk=base/'sdk/emulator';(sdk/'lib').mkdir(parents=True);(sdk/'source.properties').write_text('Pkg.Revision='+('0.0.0' if variant=='sdk' else '37.3.10'));proto=b'unit-fixture-not-SDK';(sdk/'lib/emulator_controller.proto').write_bytes(proto);(base/'render').mkdir()
   class Stub:
    def injectAudio(self,it,**kwargs):
     if variant=='anonymous_ok':return None
     raise RpcError('PERMISSION_DENIED' if variant=='anonymous_code' else 'UNAUTHENTICATED')
    def getStatus(self,*a,**kw):
     if variant=='auth':raise RpcError('UNAUTHENTICATED')
     assert kw['metadata'][0][1]=='Bearer '+secret
     return types.SimpleNamespace(version='37.3.10')
    def setMicrophoneState(self,*a,**kw):pass
    def getMicrophoneState(self,*a,**kw):return types.SimpleNamespace(realAudioEnabled=variant=='host_mic')
   google=types.ModuleType('google');google.__path__=[];protobuf=types.ModuleType('google.protobuf');protobuf.__path__=[]
   mods={'grpc':types.SimpleNamespace(RpcError=RpcError,insecure_channel=lambda _:Channel(),channel_ready_future=lambda _:types.SimpleNamespace(result=lambda **k:None)), 'emulator_controller_pb2':types.SimpleNamespace(MicrophoneState=lambda **k:types.SimpleNamespace(**k)), 'emulator_controller_pb2_grpc':types.SimpleNamespace(EmulatorControllerStub=lambda _:Stub()), 'google':google,'google.protobuf':protobuf,'google.protobuf.empty_pb2':types.SimpleNamespace(Empty=lambda:None)}
   old=Path.cwd();os.chdir(base)
   try:
    journal=m.InitJournal(base/'journal.json')
    with patch.dict(sys.modules,mods),patch.dict(os.environ,{'ANDROID_HOME':str(base/'sdk'),'RUNNER_TEMP':str(base),'XDG_RUNTIME_DIR':str(root),'M06_EMULATOR_PID':str(pid)}),patch.object(m,'PROTO_SHA',hashlib.sha256(proto).hexdigest()),patch.object(m,'owned_pid',return_value=variant!='pid'),patch.object(m.subprocess,'check_output',return_value='LISTEN 0 1 127.0.0.1:8554 0.0.0.0:*\n'):
     if variant=='success':m.GrpcMic(journal).close()
     else:
      with self.assertRaises(RuntimeError):m.GrpcMic(journal)
    row=json.loads((base/'journal.json').read_text());encoded=json.dumps(row)
    self.assertNotIn(secret,encoded);self.assertNotIn('DO_NOT_EXPORT_RPC_BODY',encoded);self.assertNotIn('authorization',encoded)
    stages={'sdk':'SDK_CHECK','mode':'PRIVATE_DIRECTORY_CHECK','pid':'DESCRIPTOR_CHECK','anonymous_ok':'ANONYMOUS_CHECK','anonymous_code':'ANONYMOUS_CHECK','auth':'AUTHENTICATED_STATUS_REQUEST','host_mic':'HOST_MIC_CHECK'}
    if variant=='success':self.assertEqual('READY',row['stage'])
    else:
     self.assertEqual(stages[variant],row['failure_stage']);self.assertTrue(row['events'][-1]['source'])
    if variant=='anonymous_code':self.assertEqual('PERMISSION_DENIED',next(e['rpc_code'] for e in row['events'] if e['stage']=='ANONYMOUS_CHECK'))
   finally:os.chdir(old)
 def test_safe_stage_failures_and_authentication_not_relaxed(self):
  for variant in ['success','sdk','mode','pid','anonymous_ok','anonymous_code','auth','host_mic']:
   with self.subTest(variant=variant):self.fixture(variant)
if __name__=='__main__':unittest.main()
