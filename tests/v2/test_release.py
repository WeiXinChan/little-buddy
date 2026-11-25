"""Synthetic V2-only files and real loopback TLS; zero supplier calls."""
import asyncio
from contextlib import redirect_stderr,redirect_stdout
from hashlib import sha256
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from backend.v2.files import ConfigurationError,read_checked
from backend.v2.preflight import prepare,CONTRACT
from backend.v2.live import cli,parser
from backend.v2.release import verify

ROOT=Path(__file__).resolve().parents[2]


class Fixture:
    def __init__(self,path):
        self.path=path
        subprocess.run(['openssl','req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256',
            '-nodes','-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1',
            '-addext','extendedKeyUsage=serverAuth','-keyout',str(path/'key'),'-out',str(path/'cert')],
            check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        (path/'cert').chmod(0o644);(path/'key').chmod(0o600)
        self.token='SyntheticV2OnlyCredential'*3
        self.write('v2-device-token',self.token)
        self.write('dashscope-api-key','SYNTHETIC_PRIVATE_PROVIDER_KEY')
        self.write('service.env','\n'.join(f'{k}={v}' for k,v in dict(DASHSCOPE_WORKSPACE='synthetic',
            DASHSCOPE_REGION='cn-beijing',DASHSCOPE_ASR_MODEL='fun-asr-realtime',DASHSCOPE_LLM_MODEL='qwen3.8-flash',
            DASHSCOPE_TTS_MODEL='cosyvoice-v3-flash',DASHSCOPE_TTS_VOICE='longanyang').items()))
        self.scope=dict(v=1,purpose='little-buddy-v2-device',endpoint='wss://v2.synthetic.invalid/v2/voice',
            token_sha256=sha256(self.token.encode()).hexdigest(),not_after=int(time.time())+3600,protocol_contract=CONTRACT)
        self.write_scope()
        with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        self.argv=['--cert',str(path/'cert'),'--key',str(path/'key'),'--token-file',str(path/'v2-device-token'),
            '--device-scope',str(path/'scope.json'),'--ca-file',str(path/'cert'),'--tls-name','127.0.0.1',
            '--service-env',str(path/'service.env'),'--credential-directory',str(path),'--apk-contract',CONTRACT,
            '--port',str(port)]
        self.args=parser().parse_args(self.argv)

    def write(self,name,value):
        path=self.path/name;path.write_text(value);path.chmod(0o600)

    def write_scope(self):self.write('scope.json',json.dumps(self.scope))


class Preflight(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.fixture=Fixture(Path(self.folder.name))

    def test_offline_entry_has_no_network_and_no_secret_or_workspace_output(self):
        out,err=io.StringIO(),io.StringIO()
        with (patch('socket.socket.connect',side_effect=AssertionError('network forbidden')),
              redirect_stdout(out),redirect_stderr(err)):
            result=cli(self.fixture.argv+['--check'])
        self.assertEqual(result,0)
        report=json.loads(out.getvalue());self.assertEqual(report['protocol_contract'],CONTRACT)
        self.assertEqual(report['ingress_tls'],'not_probed')
        for text in [self.fixture.token,'SYNTHETIC_PRIVATE_PROVIDER_KEY','synthetic.invalid','synthetic']:
            self.assertNotIn(text,out.getvalue()+err.getvalue())

    def test_key_modes_symlink_hardlink_fifo_and_untrusted_directory_rejected(self):
        root=self.fixture.path;key=root/'dashscope-api-key'
        key.chmod(0o640)
        with self.assertRaises(ConfigurationError):prepare(self.fixture.args)
        key.chmod(0o600);(root/'alias').symlink_to(key)
        with self.assertRaises(ConfigurationError):read_checked(root/'alias','provider_key')
        os.link(key,root/'hard')
        with self.assertRaises(ConfigurationError):read_checked(key,'provider_key')
        (root/'hard').unlink();os.mkfifo(root/'pipe')
        with self.assertRaises(ConfigurationError):read_checked(root/'pipe','provider_key')
        root.chmod(0o777)
        try:
            with self.assertRaises(ConfigurationError):prepare(self.fixture.args)
        finally:root.chmod(0o700)

    def test_v1_scope_hash_expiry_and_contract_mismatch_rejected(self):
        fixture=self.fixture
        for changes in [dict(purpose='little-buddy-v1'),dict(token_sha256='0'*64),
                        dict(not_after=1000),dict(protocol_contract='v1')]:
            original=dict(fixture.scope);fixture.scope.update(changes);fixture.write_scope()
            with self.assertRaisesRegex(ConfigurationError,'v2_device_scope_invalid'):prepare(fixture.args,now=lambda:1000)
            fixture.scope=original
        fixture.write_scope();fixture.args.apk_contract='v1'
        with self.assertRaisesRegex(ConfigurationError,'apk_contract_mismatch'):prepare(fixture.args)

    def test_dependency_and_model_versions_are_exact_and_config_is_not_shell(self):
        with patch('backend.v2.preflight.version',return_value='0'):
            with self.assertRaisesRegex(ConfigurationError,'dependency_version_mismatch'):prepare(self.fixture.args)
        path=self.fixture.path/'service.env';original=path.read_text()
        self.fixture.write('service.env',original.replace('qwen3.8-flash','SYNTHETIC_PRIVATE_WRONG_MODEL'))
        with self.assertRaisesRegex(ConfigurationError,'provider_model_contract_mismatch'):prepare(self.fixture.args)
        self.fixture.write('service.env',original+'\nDASHSCOPE_LLM_MODEL=$(touch NEVER_EXECUTED)')
        with self.assertRaisesRegex(ConfigurationError,'service_env_invalid'):prepare(self.fixture.args)

    def test_tls_wrong_name_key_and_untrusted_chain_rejected_without_raw_details(self):
        fixture=self.fixture;fixture.args.tls_name='wrong.synthetic.invalid'
        with self.assertRaisesRegex(ConfigurationError,'tls_chain_name_or_key_invalid'):prepare(fixture.args)
        fixture.args.tls_name='127.0.0.1';fixture.args.key=str(fixture.path/'service.env')
        out,err=io.StringIO(),io.StringIO()
        argv=list(fixture.argv);argv[argv.index('--key')+1]=fixture.args.key
        with redirect_stdout(out),redirect_stderr(err):self.assertEqual(cli(argv+['--check']),2)
        self.assertNotIn('DASHSCOPE',err.getvalue());self.assertNotIn(str(fixture.path),err.getvalue())

    def test_release_integrity_ref_and_extra_code_rejected(self):
        folder=self.fixture.path/'release';(folder/'backend/v2').mkdir(parents=True)
        raw=b'# synthetic release fixture\n';(folder/'backend/v2/live.py').write_bytes(raw)
        metadata=dict(format=1,source_sha='a'*40,protocol_contract=CONTRACT,
            files={'backend/v2/live.py':dict(size=len(raw),sha256=sha256(raw).hexdigest())})
        (folder/'assets/v2-default').mkdir(parents=True)
        assets=b'[]';(folder/'assets/v2-default/manifest.json').write_bytes(assets)
        metadata['assets_manifest_sha256']=sha256(assets).hexdigest()
        metadata['files']['assets/v2-default/manifest.json']=dict(size=len(assets),sha256=sha256(assets).hexdigest())
        (folder/'release-manifest.json').write_text(json.dumps(metadata))
        verify(folder,'a'*40)
        wrong=dict(metadata,assets_manifest_sha256='0'*64)
        (folder/'release-manifest.json').write_text(json.dumps(wrong))
        with self.assertRaisesRegex(ValueError,'assets_version_mismatch'):verify(folder,'a'*40)
        (folder/'release-manifest.json').write_text(json.dumps(metadata))
        with self.assertRaises(ValueError):verify(folder,'b'*40)
        (folder/'backend/v2/extra.py').write_text('bad')
        with self.assertRaisesRegex(ValueError,'extra_or_missing'):verify(folder,'a'*40)
        (folder/'backend/v2/extra.py').unlink();(folder/'httpx.py').write_text('shadow package')
        with self.assertRaisesRegex(ValueError,'extra_or_missing'):verify(folder,'a'*40)
        (folder/'httpx.py').unlink();(folder/'backend/v2/live.py').write_bytes(b'altered')
        with self.assertRaisesRegex(ValueError,'integrity_failed'):verify(folder,'a'*40)

    def test_control_start_stop_rollback_are_plan_only_without_apply(self):
        spec=importlib.util.spec_from_file_location('release_control',ROOT/'backend/deploy/v2-control.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with patch.object(module,'run',side_effect=AssertionError('mutation forbidden')),redirect_stdout(io.StringIO()):
            for action in ['start','check','rollback']:self.assertEqual(module.cli([action,'a'*40]),0)
            self.assertEqual(module.cli(['stop']),0)

    def test_negative_control_disabling_secret_mode_gate_is_detected(self):
        key=self.fixture.path/'dashscope-api-key';key.chmod(0o644)
        # Mutation permits a bad secret mode at the real production gate.
        import backend.v2.files as files
        original=files.checked_file
        def wrong(path,role,**kwargs):kwargs['secret']=False;return original(path,role,**kwargs)
        with patch.object(files,'checked_file',wrong):
            with self.assertRaises(AssertionError):
                with self.assertRaises(ConfigurationError):prepare(self.fixture.args)


class Loopback(unittest.IsolatedAsyncioTestCase):
    async def test_device_expiry_closes_active_scope_and_rejects_new_handshake(self):
        from websockets.asyncio.client import connect
        from backend.v2.server import voice_server
        with tempfile.TemporaryDirectory() as folder:
            fixture=Fixture(Path(folder));checked=prepare(fixture.args)
            trust=ssl.create_default_context(cafile=str(fixture.path/'cert'))
            async with voice_server('127.0.0.1',0,checked.tls,checked.token,object(),object(),
                                    expires_at=time.time()+.3) as server:
                url=f'wss://127.0.0.1:{server.sockets[0].getsockname()[1]}/v2/voice'
                async with connect(url,ssl=trust,additional_headers={'Authorization':'Bearer '+checked.token},proxy=None) as ws:
                    with self.assertRaises(Exception):await asyncio.wait_for(ws.recv(),2)
                    self.assertEqual(ws.close_code,1008)
                with self.assertRaises(Exception):
                    async with connect(url,ssl=trust,additional_headers={'Authorization':'Bearer '+checked.token},proxy=None):pass

    async def test_real_cli_tls_auth_management_and_sigterm_safe_logs_without_cloud(self):
        from websockets.asyncio.client import connect
        with tempfile.TemporaryDirectory() as folder:
            fixture=Fixture(Path(folder));trust=ssl.create_default_context(cafile=str(fixture.path/'cert'))
            notification=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
            notification.bind(str(Path(folder)/'notify.sock'));notification.setblocking(False)
            self.addCleanup(notification.close)
            environment=dict(os.environ,NOTIFY_SOCKET=str(Path(folder)/'notify.sock'))
            child=await asyncio.create_subprocess_exec(sys.executable,'-B','-m','backend.v2.live',*fixture.argv,
                cwd=ROOT,env=environment,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            initial=b''
            try:
                initial=await asyncio.wait_for(child.stderr.readline(),5)
                self.assertEqual(json.loads(initial)['event'],'ready_loopback')
                self.assertEqual(await asyncio.wait_for(asyncio.get_running_loop().sock_recv(notification,128),1),b'READY=1')
                url=f'wss://127.0.0.1:{fixture.args.port}/v2/voice'
                with self.assertRaises(Exception):
                    async with connect(url,ssl=trust,additional_headers={'Authorization':'Bearer wrong'},proxy=None):pass
                async with connect(url,ssl=trust,additional_headers={'Authorization':'Bearer '+fixture.token},proxy=None) as ws:
                    await ws.send(json.dumps(dict(v=2,type='scope',epoch=0,seq=0)))
                    scope=json.loads(await ws.recv())
                    self.assertEqual(scope['protocol_contract'],CONTRACT)
                    await ws.send(json.dumps(dict(v=2,type='management_pause',epoch=1,seq=0,
                        session=scope['session'],turn=scope['turn'],revision=1)))
                    events=[]
                    while not events or events[-1]['type']!='management_state':events.append(json.loads(await ws.recv()))
                    paused=events[-1];self.assertEqual(paused['state'],'paused')
                    await ws.send(json.dumps(dict(v=2,type='management_resume',epoch=2,seq=0,session=scope['session'],
                        turn=scope['turn'],revision=2,pause=paused['pause'])))
                    self.assertEqual(json.loads(await ws.recv())['state'],'waiting_wake')
                    await ws.send('{"v":2,"PRIVATE_CANARY":"SYNTHETIC_PRIVATE_AUDIO"}')
                    with self.assertRaises(Exception):await ws.recv()
                child.terminate();out,err=await asyncio.wait_for(child.communicate(),5)
                self.assertEqual(child.returncode,0)
                self.assertIn(b'"event": "stopped"',err)
                for value in [fixture.token,'PRIVATE_CANARY','SYNTHETIC_PRIVATE_AUDIO','SYNTHETIC_PRIVATE_PROVIDER_KEY',folder]:
                    self.assertNotIn(value,(initial+out+err).decode())
            finally:
                if child.returncode is None:
                    child.terminate();await asyncio.wait_for(child.communicate(),5)
