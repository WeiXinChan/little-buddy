"""Explicit model selection with actual HTTP adapters/VoicePeer, no cloud."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import httpx
from backend.dashscope import DashScope
from backend.v2.companion import UnifiedProviders,DashScopeModel,ModelError
from backend.v2.models import TEXT_MODEL,TEXT_MODELS,IMAGE_REVIEW_MODEL,model_policy
from backend.v2.runtime import settings,providers,manifest
from backend.v2.preflight import prepare
from backend.v2.files import ConfigurationError
from backend.v2.image_review import ModelImageReview
from backend.v2.dynamic_images import ImageFailure
from scripts.v2_multiturn_probe import run_case,ProbeLimit
from tests.v2 import test_multiturn_probe as fixtures
from tests.v2.test_safety_help import CONFIG
from tests.v2.test_release import Fixture
from tests.v2.test_m05 import Speech
from tests.v2.test_image_review import Stream,NONCE,PNG

class Flash(unittest.IsolatedAsyncioTestCase):
    def model(self,http,model=TEXT_MODEL):
        return DashScopeModel(DashScope(http,workspace='synthetic',region='cn-beijing',key='SYNTHETIC',
            asr='fake',llm=model,tts='fake',voice='fake'))

    async def exercise(self,*,bad=None):
        calls=[]
        async def response(request):
            body=json.loads(request.content);calls.append(body)
            instruction=body['messages'][0]['content'];data=json.loads(body['messages'][1]['content'])
            if bad=='quota':return httpx.Response(403,json={'error':{'code':'AllocationQuota.FreeTierOnly'}})
            if '审核下一个' in instruction:value={'allow':False if bad=='deny' else True,'quality':True}
            elif '提取孩子' in instruction:value={'facts':[{'key':'rule','value':'FORGED' if bad=='facts' else data['text']}]}
            else:
                value={'action':'continue','mode':'story','rules':'轮流编故事','roles':['小猫'],'secrets':{},
                       'sentences':['猫船长出发。'],'anchors':{}}
                if bad=='plan':value['mode']='invented'
                if bad=='rules':value['rules']=[]
                if bad=='roles':value['roles']='captain'
                if bad=='anchors':value['anchors']={'plot.main':99}
            raw='{"allow":true,"allow":false}' if bad=='duplicate' and '审核下一个' in instruction else json.dumps(value,ensure_ascii=False)
            return httpx.Response(200,json={'choices':[{'message':{'content':raw}}], 'usage':{'prompt_tokens':10,'completion_tokens':2}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
            model=self.model(http);speech=Speech();bundle=UnifiedProviders(speech,model)
            report=await run_case(fixtures.CASE,bundle)
            metrics=model.metrics()
        return report,calls,metrics

    async def test_selected_default_flash_real_voicepeer_json_object_and_usage(self):
        report,calls,metrics=await self.exercise()
        self.assertEqual(len(report['turns']),3)
        self.assertTrue(all(all(t['checks'].values()) for t in report['turns']))
        self.assertTrue(all(c['model']==TEXT_MODEL and c['response_format']=={'type':'json_object'} and c['enable_thinking'] is False for c in calls))
        self.assertEqual(report['usage']['requests'],len(calls));self.assertEqual(report['usage']['prompt_tokens'],10*len(calls))
        self.assertEqual(metrics['model'],TEXT_MODEL);self.assertIsNone(metrics['cost']['monetary'])

    async def test_invalid_plan_fact_safety_or_duplicate_json_never_passes_delivery(self):
        for bad in ('plan','rules','roles','anchors','facts','deny','duplicate'):
            report,calls,metrics=await self.exercise(bad=bad)
            self.assertFalse(report['turns'][0]['checks']['delivery']);self.assertEqual(report['tts_requests'],0)
            self.assertTrue(all(c['model']==TEXT_MODEL for c in calls))

    async def test_free_only_error_does_not_try_another_or_paid_model(self):
        report,calls,metrics=await self.exercise(bad='quota')
        self.assertFalse(report['turns'][0]['checks']['delivery'])
        self.assertEqual([c['model'] for c in calls],[TEXT_MODEL])
        self.assertEqual(metrics['usage_missing']['prompt_tokens'],1) # no usage receipt, not zero-cost proof
        self.assertIsNone(report['usage']['prompt_tokens'])

    async def test_allowlist_model_schema_and_probe_admission_are_exact(self):
        self.assertEqual(TEXT_MODEL,'deepseek-v4.1-flash-1017');self.assertEqual(IMAGE_REVIEW_MODEL,'qwen4-max')
        for bad in ('qwen3.8-omni-flash','deepseek-typo','qwen3.8-flash',''):
            config=dict(CONFIG,DASHSCOPE_LLM_MODEL=bad)
            with self.assertRaises(ValueError):settings(environment=config)
            if bad:
                with self.assertRaises(ValueError):self.model(None,bad)
        configured=self.model(None)
        for invalid in ('',[],{}):
            with self.assertRaises(ValueError):DashScopeModel(configured.speech,model=invalid)
        calls=[]
        async def response(request):calls.append(json.loads(request.content));return httpx.Response(200,json={'choices':[{'message':{'content':'{}'}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
            for candidate in sorted(TEXT_MODELS):await self.model(http,candidate).complete('synthetic',{},schema={'type':'object'})
        for request in calls:
            self.assertEqual(request['response_format']['type'],'json_schema' if request['model']=='qwen4-max' else 'json_object')
        invalid=fixtures.Probe().providers();invalid.model.model='qwen3.8-omni-flash'
        with self.assertRaises(ProbeLimit):await run_case(fixtures.CASE,invalid)

    async def test_visual_review_remains_qwen4_regardless_text_choice(self):
        calls=[]
        async def response(request):calls.append(json.loads(request.content));return httpx.Response(200,headers={'content-type':'application/json'},stream=Stream(json.dumps({'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'{\"allow\":true}'}}]}).encode()))
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
            text=self.model(http)
            review=ModelImageReview(http,workspace='synthetic',region='cn-beijing',api_key='SYNTHETIC',prompt_policy='prompt-v1',image_policy='image-v1')
            await review.prompt('儿童插画：猫',NONCE)
            await review.image(PNG,NONCE)
            self.assertEqual(text.model,TEXT_MODEL);self.assertEqual([c['model'] for c in calls],['qwen4-max','qwen4-max'])
            with self.assertRaises(ImageFailure):ModelImageReview(http,workspace='synthetic',region='cn-beijing',api_key='SYNTHETIC',prompt_policy='p',image_policy='i',model=TEXT_MODEL)

    async def test_preflight_accepts_explicit_candidates_rejects_omni_and_identity_is_honest(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture=Fixture(Path(directory));original=(fixture.path/'service.env').read_text()
            for candidate in sorted(TEXT_MODELS):
                fixture.write('service.env',original.replace('qwen4-max',candidate))
                prepared=prepare(fixture.args)
                self.assertEqual(prepared.report['models']['llm'],candidate)
                self.assertEqual(prepared.report['model_policy']['image_review'],'qwen4-max')
                self.assertFalse(prepared.report['model_policy']['automatic_fallback'])
            fixture.write('service.env',original.replace('qwen4-max','qwen3.8-omni-flash'))
            with self.assertRaisesRegex(ConfigurationError,'provider_model_contract_mismatch'):prepare(fixture.args)

    async def test_release_identity_binds_default_text_and_independent_review(self):
        import subprocess,tarfile
        from backend.v2.release import package,verify
        source=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);archive=root/'release.tar.gz';package(source,archive)
            folder=root/'release';folder.mkdir()
            with tarfile.open(archive) as tar:tar.extractall(folder,filter='data')
            identity=verify(folder,source)
            self.assertEqual(identity['models']['llm'],TEXT_MODEL)
            self.assertEqual(identity['model_policy']['image_review'],IMAGE_REVIEW_MODEL)
            self.assertFalse(identity['model_policy']['automatic_fallback'])
            identity['model_policy']['image_review']=TEXT_MODEL
            (folder/'release-manifest.json').write_text(json.dumps(identity))
            with self.assertRaisesRegex(ValueError,'release_model_policy_mismatch'):verify(folder,source)

    async def test_package_cannot_label_old_model_source_as_new_default(self):
        from backend.v2.release import package,LOG_POLICY_FILES
        from unittest.mock import patch
        import subprocess
        # This historic source predates the separate log namespace. Supply only
        # the current reviewed log-policy prerequisites; keep its actual old
        # model/source bytes so package reaches the intended model rejection.
        real_output=subprocess.check_output; supplied=set()
        def prerequisite_fixture(command,**kwargs):
            if command[:2]==['git','ls-tree']:
                paths=real_output(command,**kwargs).splitlines()
                return '\n'.join(sorted(set(paths)|LOG_POLICY_FILES))+'\n'
            if command[:2]==['git','show']:
                path=command[2].split(':',1)[1]
                if path in LOG_POLICY_FILES:
                    supplied.add(path);return Path(path).read_bytes()
            return real_output(command,**kwargs)
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'release.tar.gz'
            with patch('backend.v2.release.subprocess.check_output',side_effect=prerequisite_fixture):
                with self.assertRaisesRegex(ValueError,'release_source_model_mismatch'):
                    package('4f991de1e2f18eb3f79db03ee1b217a6d4daa0db',output)
            self.assertEqual(supplied,LOG_POLICY_FILES)
            self.assertFalse(output.exists())

    async def test_formal_live_entry_uses_selected_model_and_v2_release_adapter(self):
        from contextlib import asynccontextmanager
        from types import SimpleNamespace
        import time
        from unittest.mock import patch
        from backend.v2.live import serve_checked
        from backend.v2.preflight import MODELS
        from backend.v2.speech import V2Speech
        seen=[]
        @asynccontextmanager
        async def http():yield object() # any cloud request fails rather than reaching network
        @asynccontextmanager
        async def server(host,port,tls,token,bundle,policy,**kwargs):
            self.assertEqual((host,port),('127.0.0.1',19483))
            self.assertIsInstance(bundle.speech,V2Speech)
            self.assertEqual(bundle.model.model,TEXT_MODEL)
            self.assertIs(bundle.model.speech,bundle.speech);seen.append(True)
            yield object()
        prepared=SimpleNamespace(provider_key='SYNTHETIC',tls=None,token='SYNTHETIC',
            config=dict(workspace='synthetic',region='cn-beijing',**MODELS),expires_at=int(time.time())+60)
        stop=asyncio.Event();stop.set()
        with patch('backend.dashscope.http_client',http),patch('backend.v2.server.voice_server',server),patch('backend.v2.live.notify_ready'),patch('backend.v2.files.disable_core_dumps'):
            await serve_checked(SimpleNamespace(port=19483),prepared,stop=stop)
        self.assertEqual(seen,[True])
