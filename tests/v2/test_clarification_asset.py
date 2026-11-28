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
    def test_production_source_files_pin_original_git_objects(self):
        # Tool commit is provided after freeze; production identity is independent.
        import subprocess
        for name in tool.PRODUCTION:
            raw=subprocess.check_output(['git','show',tool.SOURCE+':'+name],cwd=tool.ROOT)
            self.assertEqual(raw,(tool.ROOT/name).read_bytes())
