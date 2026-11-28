import asyncio,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import asynccontextmanager
from scripts import v2_clarification_asset as tool
from backend.dashscope import SpeechTask,ProviderError,SpeechTaskError

class Socket:
    def __init__(self,events):self.events=events;self.commands=[];self.id=None
    async def send(self,raw):
        value=json.loads(raw);self.id=value['header']['task_id'];self.commands.append(value)
    async def recv(self):return self.event(self.events.pop(0))
    def event(self,e):
        if isinstance(e,bytes):return e
        event,usage=e
        return json.dumps(dict(header=dict(task_id=self.id,event=event),payload={'usage':{'characters':usage}}))
    def __aiter__(self):return self
    async def __anext__(self):
        if not self.events:raise StopAsyncIteration
        return self.event(self.events.pop(0))

class Asset(unittest.IsolatedAsyncioTestCase):
    def speech(self):
        return tool.AssetSpeech(None,key='SYNTHETIC',workspace='synthetic',region='cn-beijing',asr='unused',llm='unused',tts=tool.MODEL,voice=tool.VOICE)
    async def test_exact_production_payload_usage_not_sum_and_no_second_io(self):
        s=self.speech();socket=Socket([('task-started',None),('result-generated',5),b'\1\0'*10,('result-generated',13),('task-finished',13)])
        entered=0
        @asynccontextmanager
        async def port(owner):
            nonlocal entered;entered+=1;yield socket
        with patch('backend.v2.speech.V2Speech.speech_socket',port):
            async with s.synthesize(tool.TEXT,tool.RATE) as chunks:audio=b''.join([chunk async for chunk in chunks])
            with self.assertRaises(tool.GuardError):
                async with s.synthesize(tool.TEXT,tool.RATE):pass
        self.assertEqual((s.attempts,entered),(1,1));self.assertEqual(len(audio),20)
        self.assertEqual((s.usage_final,s.usage_max,s.finished),(13,13,True))
        self.assertEqual([c['header']['action'] for c in socket.commands],['run-task','continue-task','finish-task'])
        request=socket.commands[0]['payload'];self.assertEqual((request['task'],request['function'],request['model']),('tts','SpeechSynthesizer',tool.MODEL))
        self.assertEqual(request['parameters'],dict(text_type='PlainText',voice='longanyang',format='pcm',sample_rate=24000,enable_ssml=False))
        self.assertEqual(socket.commands[1]['payload']['input'],{'text':tool.TEXT})
    async def test_fixed_text_rate_and_asr_admission(self):
        s=self.speech()
        for text,rate in [('other',tool.RATE),(tool.TEXT,16000)]:
            with self.assertRaises(tool.GuardError):s.synthesize(text,rate)
        with self.assertRaises(tool.GuardError):s.recognize(16000)
        self.assertEqual(s.attempts,0)
    async def test_wrong_task_usage_rejected_and_unfinished_not_success(self):
        s=self.speech();socket=Socket([('task-finished',999)]);task=SpeechTask(socket);socket.id='wrong'
        with self.assertRaises(ProviderError):
            async for _ in s.audio(task):pass
        self.assertIsNone(s.usage_max);self.assertFalse(s.finished)
        socket=Socket([]);task=SpeechTask(socket)
        with self.assertRaises(ProviderError):
            async for _ in s.audio(task):pass
    async def test_missing_terminal_usage_uses_valid_max_only(self):
        s=self.speech();socket=Socket([('result-generated',7),('result-generated',True),('task-finished',None)])
        task=SpeechTask(socket);socket.id=task.id
        async for _ in s.audio(task):pass
        self.assertEqual(s.usage_max,7);self.assertIsNone(s.usage_final)
    async def test_task_failure_preserves_error_without_usage_or_success(self):
        s=self.speech()
        class Failed(Socket):
            def event(self,e):
                return json.dumps(dict(header=dict(task_id=self.id,event='task-failed',error_code='AllocationQuota.FreeTierOnly',error_message='PRIVATE_PROVIDER_BODY'),payload={}))
        socket=Failed([None]);task=SpeechTask(socket);socket.id=task.id
        with self.assertRaises(SpeechTaskError):
            async for _ in s.audio(task):pass
        self.assertFalse(s.finished);self.assertIsNone(s.usage_final)
    def test_default_disabled_does_not_read_config_or_open_socket(self):
        with patch.object(tool,'load_config',side_effect=AssertionError()):self.assertEqual(tool.main([]),0)
    def test_production_model_mismatch_rejected(self):
        with patch.object(tool,'settings',return_value={'tts':'other','voice':tool.VOICE}):
            with self.assertRaises(tool.GuardError):tool.load_config()
    def test_private_output_and_original_bytes_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'run';tool.private_output(out)
            self.assertEqual(out.stat().st_mode&0o777,0o700)
            with self.assertRaises(tool.GuardError):tool.private_output(out)
            pcm=b'\1\0'*10;(out/'clarification.pcm').write_bytes(pcm);os.chmod(out/'clarification.pcm',0o600)
            report=tool.plan();report.update(tool_source='fixed',tool_sha256=tool.digest(Path(tool.__file__).read_bytes()),calls=dict(tts=1,asr=0,llm=0,image=0),tts_attempts=1,terminal='asset_generated_not_auditioned',task_finished=True,
                cleanup={'confirmed':True,'pending':0},pcm_sha256=tool.digest(pcm),samples=10,pcm_bytes=20)
            tool.save(out/'result.json',report)
            self.assertEqual(tool.validate_result(out,'fixed')[:2],(True,True))
            report['cleanup']['pending']=1;tool.save(out/'result.json',report)
            self.assertEqual(tool.validate_result(out,'fixed')[:2],(False,False))
            self.assertEqual((out/'result.json').stat().st_mode&0o777,0o600)
    def test_parent_binding_rejects_other_pid_or_reused_start(self):
        with self.assertRaises(tool.GuardError):tool.parent_guard(-1,'0')
        with patch.object(tool,'process_start',return_value='22'):
            with self.assertRaises(tool.GuardError):tool.parent_guard(os.getppid(),'21')
    def test_smoke_does_not_load_credentials_or_call_generate(self):
        # Actual wrapper counterpart executes in a separate real systemd cgroup.
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'run';out.mkdir(mode=0o700);tool.save(out/'purpose.json',dict(purpose='clarification',tool_source='fixed'))
            with patch.object(tool,'source_guard'),patch.object(tool,'supervisor_guard',return_value={'build_cgroup':True}),patch.object(tool,'parent_guard'),patch.object(tool,'load_config',side_effect=AssertionError('no config')),patch.object(tool,'generate',side_effect=AssertionError('no provider')):
                self.assertEqual(tool.main(['--admission-smoke','--worker','--tool-source','fixed','--output',str(out),'--parent-pid',str(os.getppid()),'--parent-start','fixed']),0)
            value=json.loads((out/'admission.json').read_text());self.assertEqual(value['calls'],dict(tts=0,asr=0,llm=0,image=0))
    def test_production_source_files_pin_original_git_objects(self):
        # Historical identity is independent of future production working trees.
        import subprocess
        expected={'backend/dashscope.py': 'b90f68944b7de1bef32da3e0a962599027b713fb8ae7718a62d6af78ccb269e2', 'backend/timing.py': 'fad4a5646e2fd4e53c1bc1f3cb18fe2ac4e5a44d3344d3409b3f38b996850e95', 'backend/v2/speech.py': '79ed4eb773e4c2e61341835197bdc1936a50f0094fa664c24a5ca280f7c630d2', 'backend/v2/runtime.py': '585a4b4b5b19513c8fa9a0452d7304594f9c56b00de3a6d14977e42d672607f4', 'backend/v2/files.py': 'ddabea2536e80877c8ebaf19b7b8ba641a7c551bf9690cd73765ddd6ddb26b99'}
        for name,sha in expected.items():
            raw=subprocess.check_output(['git','show',tool.SOURCE+':'+name],cwd=tool.ROOT)
            self.assertEqual(tool.digest(raw),sha)
    def test_execution_source_guard_still_rejects_modified_local_bytes(self):
        import subprocess
        real=tool.ROOT;original=subprocess.run
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);name=tool.PRODUCTION[0];(root/name).parent.mkdir(parents=True)
            (root/name).write_bytes(b'SYNTHETIC_CHANGED_SOURCE')
            def git_object(*args,**kwargs):
                kwargs['cwd']=real;result=original(*args,**kwargs)
                self.assertEqual(result.returncode,0);return result
            with patch.object(tool,'ROOT',root),patch.object(tool.subprocess,'run',git_object):
                with self.assertRaises(tool.GuardError):tool.source_guard(tool.SOURCE)

class Purpose(unittest.TestCase):
    def test_default_and_service_are_distinct_fixed_material(self):
        self.assertEqual(tool.plan()['text'],tool.TEXT)
        self.assertEqual(tool.plan('service-failure')['text'],'刚才没能回答，你可以再叫我一次。')
        self.assertEqual(tool.plan('service-failure')['filename'],'service-failure.pcm')
        with self.assertRaises(tool.GuardError):tool.plan('other')
    def test_service_cannot_synthesize_old_or_arbitrary_text(self):
        s=tool.AssetSpeech(None,key='SYNTHETIC',workspace='synthetic',region='cn-beijing',asr='unused',llm='unused',tts=tool.MODEL,voice=tool.VOICE,purpose='service-failure')
        for text in [tool.TEXT,'arbitrary']:
            with self.assertRaises(tool.GuardError):s.synthesize(text,24000)
        self.assertEqual(s.attempts,0)
    def test_worker_rejects_cross_purpose_before_generate(self):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t);tool.save(out/'purpose.json',dict(purpose='clarification',tool_source='fixed'))
            with patch.object(tool,'source_guard'),patch.object(tool,'supervisor_guard'),patch.object(tool,'generate',side_effect=AssertionError('no call')):
                with self.assertRaises(tool.GuardError):tool.main(['--admission-smoke','--worker','--tool-source','fixed','--purpose','service-failure','--output',t])
    def test_parent_validates_expected_purpose(self):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t);tool.save(out/'result.json',dict(tool.plan('clarification'),tool_source='fixed'))
            self.assertFalse(tool.validate_result(out,'fixed','service-failure')[0])
