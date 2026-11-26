"""Temporary deployment inputs only. Never starts systemd/services or reads /etc."""
from contextlib import redirect_stdout,redirect_stderr
from hashlib import sha256
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from backend.v2.live import cli,parser
from backend.v2.preflight import prepare,CONTRACT,MODELS
from backend.v2.models import model_policy
from backend.v2.image_runtime import PROMPT_POLICY,IMAGE_POLICY

ROOT=Path(__file__).resolve().parents[2]
UNIT=ROOT/'backend/deploy/v2-little-buddy.service'
SPEC=importlib.util.spec_from_file_location('deploy_inputs_control',ROOT/'backend/deploy/v2-control.py')
CONTROL=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(CONTROL)
EVIDENCE=ROOT/'docs/testing/v2/deploy-inputs'


def live_commands(text):
    return [shlex.split(line.split('=',1)[1]) for line in text.splitlines()
            if line.startswith(('ExecStart=','ExecStartPre=')) and '-m backend.v2.live ' in line]


class DeployInputs(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name);self.config=self.root/'config';self.config.mkdir(mode=0o700)
        self.state=self.root/'state/feedback';self.state.mkdir(parents=True,mode=0o700)
        self.sha='a'*40;self.release=self.root/'releases'/self.sha
        (self.release/'.venv/bin').mkdir(parents=True);(self.release/'.venv/bin/python').symlink_to(sys.executable)
        for name in ('v2-little-buddy.service','v2-control.py'):
            target=self.release/'backend/deploy'/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/'backend/deploy'/name,target)
        assets=self.release/'assets/v2-default/manifest.json';assets.parent.mkdir(parents=True);assets.write_text('[]')
        inventory={p.relative_to(self.release).as_posix():dict(size=p.stat().st_size,sha256=sha256(p.read_bytes()).hexdigest())
                   for p in self.release.rglob('*') if p.is_file() and '.venv' not in p.parts}
        (self.release/'release-manifest.json').write_text(json.dumps(dict(format=1,source_sha=self.sha,models=MODELS,model_policy=model_policy(),
            protocol_contract=CONTRACT,assets_manifest_sha256=sha256(assets.read_bytes()).hexdigest(),files=inventory)))
        subprocess.run(['openssl','req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256',
            '-nodes','-days','1','-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1',
            '-addext','extendedKeyUsage=serverAuth','-keyout',str(self.config/'tls-private-key.pem'),
            '-out',str(self.config/'tls-certificate.pem')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for p in self.config.iterdir():p.chmod(0o600)
        shutil.copyfile(self.config/'tls-certificate.pem',self.config/'trust-anchor.pem')
        (self.config/'trust-anchor.pem').chmod(0o600)
        token='SyntheticV2OnlyToken'*3
        self.write('v2-device-token',token);self.write('dashscope-api-key','SYNTHETIC_PROVIDER_KEY')
        for name in ('dashscope-image-key','dashscope-review-key'):self.write(name,'SYNTHETIC_ONLY_'+name)
        self.write('service.env','\n'.join(f'{k}={v}' for k,v in dict(DASHSCOPE_WORKSPACE='synthetic',
            DASHSCOPE_REGION='cn-beijing',DASHSCOPE_ASR_MODEL='fun-asr-realtime',DASHSCOPE_LLM_MODEL='qwen4-max',
            DASHSCOPE_TTS_MODEL='cosyvoice-v3-flash',DASHSCOPE_TTS_VOICE='longanyang').items()))
        self.write('device-scope.json',json.dumps(dict(v=1,purpose='little-buddy-v2-device',
            endpoint='wss://fixture.invalid/v2/voice',token_sha256=sha256(token.encode()).hexdigest(),
            not_after=int(time.time())+3600,protocol_contract=CONTRACT)))
        self.image=dict(enabled=True,region='cn-beijing',workspace='synthetic',model='qwen-image-3.0',
            review_model='qwen4-max',resource_review_id='synthetic-fixture-only',prompt_policy=PROMPT_POLICY,
            image_policy=IMAGE_POLICY,width=512,height=512,timeout=8,result_ttl=15)
        self.write('image.json',json.dumps(self.image))
        self.argv=['--check','--port','19483','--cert',str(self.config/'tls-certificate.pem'),
            '--key',str(self.config/'tls-private-key.pem'),'--ca-file',str(self.config/'trust-anchor.pem'),
            '--tls-name','127.0.0.1','--token-file',str(self.config/'v2-device-token'),
            '--device-scope',str(self.config/'device-scope.json'),'--service-env',str(self.config/'service.env'),
            '--credential-directory',str(self.config),'--image-config',str(self.config/'image.json'),
            '--feedback-database',str(self.state/'issues.sqlite'),'--apk-contract',CONTRACT]

    def write(self,name,value):
        path=self.config/name;path.write_text(value);path.chmod(0o600)

    def invoke(self,argv=None):
        out,err=io.StringIO(),io.StringIO()
        with (patch('backend.v2.live.serve_checked',side_effect=AssertionError('must not serve')),
              patch('socket.socket.connect',side_effect=AssertionError('must not connect')),
              patch('socket.socket.bind',side_effect=AssertionError('must not bind')),
              redirect_stdout(out),redirect_stderr(err)):
            result=cli(self.argv if argv is None else argv)
        for secret in ('SyntheticV2OnlyToken','SYNTHETIC_PROVIDER','SYNTHETIC_ONLY','fixture.invalid','synthetic'):
            self.assertNotIn(secret,out.getvalue()+err.getvalue())
        return result,out.getvalue(),err.getvalue()

    def test_unit_check_start_inputs_identical_and_private_dynamic_state(self):
        text=UNIT.read_text();check,start=live_commands(text)
        self.assertIn('--check',check);check.remove('--check');self.assertEqual(check,start)
        for name in ('image.json','dashscope-image-key','dashscope-review-key'):
            self.assertIn('LoadCredential='+name+':/etc/little-buddy-v2/'+name,text)
        self.assertEqual(start[start.index('--image-config')+1],'%d/image.json')
        self.assertEqual(start[start.index('--feedback-database')+1],'%S/little-buddy-v2/feedback/issues.sqlite')
        self.assertIn('StateDirectory=little-buddy-v2\nStateDirectoryMode=0700',text)
        self.assertIn('DynamicUser=yes',text);self.assertIn('ProtectSystem=strict',text)
        self.assertNotIn('--feedback-copies-policy',text);self.assertNotIn('single-store-no-exports-v1',text)
        self.assertLess(text.index('backend.v2.release verify'),text.index('/usr/bin/install -d'))
        self.assertIn('/usr/bin/install -d -m 0700 %S/little-buddy-v2/feedback',text)

    def test_real_control_release_verify_and_preflight_no_db_no_service(self):
        commands=[];reports=[]
        def real_run(command,*,cwd):
            self.assertNotIn('systemctl',command);commands.append(command)
            env=dict(os.environ,PYTHONPATH=str(ROOT),PYTHONDONTWRITEBYTECODE='1')
            result=subprocess.run(command,cwd=cwd,env=env,capture_output=True,text=True,check=True)
            reports.append(json.loads(result.stdout))
        before=sorted(p.name for p in self.state.iterdir())
        with patch.multiple(CONTROL,ROOT=self.root,CONFIG=self.config,STATE=self.state),patch.object(CONTROL,'run',side_effect=real_run):
            self.assertEqual(CONTROL.checked_release(self.sha),self.release)
        self.assertEqual(reports[0],{'release':'verified'})
        self.assertEqual(reports[1]['dynamic_images'],'configured_not_cloud_verified')
        self.assertEqual(reports[1]['feedback_provider'],'self_hosted_configured_not_accepted')
        self.assertEqual(sorted(p.name for p in self.state.iterdir()),before)
        self.assertEqual(len(commands),2);self.assertIn('--check',commands[1]);self.assertNotIn('--feedback-copies-policy',commands[1])
        runtime=prepare(parser().parse_args(self.argv))
        self.assertFalse(runtime.feedback.copies_reviewed);self.assertIsNotNone(runtime.images)
        self.assertFalse((self.state/'issues.sqlite').exists())
        if EVIDENCE.exists():(EVIDENCE/'temporary-preflight.json').write_text(json.dumps(dict(
            source='temporary synthetic fixture only',release_verify=reports[0],offline_preflight=reports[1],
            feedback_database_created=False,feedback_copies_reviewed=runtime.feedback.copies_reviewed,
            services_started=0,cloud_calls=0),indent=2)+'\n')

    def test_missing_bad_image_sources_or_old_review_model_fail_closed(self):
        for name in ('image.json','dashscope-image-key','dashscope-review-key'):
            path=self.config/name;raw=path.read_bytes();path.unlink()
            try:
                self.assertEqual(self.invoke()[0],2)
                with patch.object(CONTROL,'CONFIG',self.config):
                    with self.assertRaises((ValueError,OSError)):CONTROL.checked_image_sources()
            finally:path.write_bytes(raw);path.chmod(0o600)
        self.write('image.json',json.dumps(dict(self.image,review_model='qwen3.8-flash')))
        self.assertEqual(self.invoke()[0],2)
        self.write('image.json',json.dumps(self.image));(self.config/'dashscope-review-key').chmod(0o644)
        self.assertEqual(self.invoke()[0],2)
        self.assertFalse((self.state/'issues.sqlite').exists())

    def test_missing_or_nonprivate_feedback_parent_rejected_without_creation(self):
        self.state.rmdir();self.assertEqual(self.invoke()[0],2);self.assertFalse(self.state.exists())
        self.state.mkdir(mode=0o755);self.assertEqual(self.invoke()[0],2)
        self.state.chmod(0o700);result,_,_=self.invoke();self.assertEqual(result,0)
        self.assertFalse((self.state/'issues.sqlite').exists())

    def test_root_sources_and_systemd_readonly_credential_modes_are_distinct(self):
        with patch.object(CONTROL,'CONFIG',self.config):
            CONTROL.checked_image_sources()
            (self.config/'dashscope-image-key').chmod(0o400)
            with self.assertRaises(ValueError):CONTROL.checked_image_sources()
            (self.config/'dashscope-image-key').chmod(0o600)
        # Emulate systemd's read-only copies, not a DynamicUser/sandbox execution proof.
        for p in self.config.iterdir():p.chmod(0o400)
        self.config.chmod(0o500)
        self.assertEqual(self.invoke()[0],0)
        self.config.chmod(0o700)

    def test_dynamic_state_symlink_ancestor_accepts_real_feedback_child_not_leaf_alias(self):
        target=self.root/'private/little-buddy-v2';target.mkdir(parents=True,mode=0o700)
        feedback=target/'feedback';feedback.mkdir(mode=0o700)
        visible=self.root/'visible-state';visible.symlink_to(target,target_is_directory=True)
        argv=[str(visible/'feedback/issues.sqlite') if value==str(self.state/'issues.sqlite') else value for value in self.argv]
        self.assertEqual(self.invoke(argv)[0],0);self.assertFalse((feedback/'issues.sqlite').exists())
        (visible/'bad-parent').symlink_to(feedback,target_is_directory=True)
        argv=[str(visible/'bad-parent/issues.sqlite') if value==str(visible/'feedback/issues.sqlite') else value for value in argv]
        self.assertEqual(self.invoke(argv)[0],2)

    def test_control_check_never_selects_or_runs_systemctl_and_plan_is_read_free(self):
        with (patch.object(CONTROL,'checked_release',side_effect=AssertionError('no read on plan')),
              patch.object(CONTROL,'run',side_effect=AssertionError('no service action')),
              redirect_stdout(io.StringIO())):
            self.assertEqual(CONTROL.cli(['start',self.sha]),0)
        calls=[]
        with (patch('os.geteuid',return_value=0),patch.object(CONTROL,'checked_release',side_effect=lambda _:calls.append('check')),
              patch.object(CONTROL,'select',side_effect=AssertionError('must not select')),
              patch.object(CONTROL,'run',side_effect=AssertionError('must not systemctl')),
              redirect_stdout(io.StringIO())):
            self.assertEqual(CONTROL.cli(['check',self.sha,'--apply']),0)
        self.assertEqual(calls,['check'])

    def test_actual_systemd_analyze_syntax_with_temporary_executable_and_credentials(self):
        text=UNIT.read_text().replace('/opt/little-buddy-v2/current/.venv/bin/python',sys.executable)
        text=text.replace('WorkingDirectory=/opt/little-buddy-v2/current','WorkingDirectory='+str(self.release))
        text=text.replace('/etc/little-buddy-v2',str(self.config))
        path=self.root/'wali-v2-deploy-fixture.service';path.write_text(text)
        result=subprocess.run(['systemd-analyze','verify','--man=no',str(path)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse((self.state/'issues.sqlite').exists())
        if EVIDENCE.exists():
            (EVIDENCE/'systemd-syntax.log').write_text('systemd-analyze verify --man=no temporary-unit\n'
                'Production python/WorkingDirectory/credential-source paths replaced with temporary fixture paths only.\n'
                'No unit installed, no service started, no credentials acquired.\nexit='+str(result.returncode)+'\n'+result.stdout+result.stderr)
