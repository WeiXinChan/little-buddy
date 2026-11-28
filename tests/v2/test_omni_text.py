"""Exact Qwen3.8 text HTTP adapter and production gates; no provider requests."""
import json,unittest,httpx
from backend.dashscope import DashScope
from backend.v2.companion import DashScopeModel,ModelError,UnifiedProviders
from backend.v2.voice import VoiceFault
from backend.v2.models import OMNI_TEXT_MODEL
from tests.v2 import test_visible_model_contracts as contracts

class OmniContracts(contracts.Contracts):
    model_name=OMNI_TEXT_MODEL

class OmniTransport(unittest.IsolatedAsyncioTestCase):
    async def model(self,handler):
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler));self.addAsyncCleanup(http.aclose)
        return DashScopeModel(DashScope(http,workspace='synthetic',region='cn-beijing',key='SYNTHETIC',
            asr='fake',llm=OMNI_TEXT_MODEL,tts='fake',voice='fake'))
    async def test_quota_auth_network_never_switch_model_or_retry(self):
        for status,code in ((403,'AllocationQuota.FreeTierOnly'),(429,'insufficient_quota'),(403,'AccessDenied')):
            calls=[]
            async def handler(request):
                calls.append(json.loads(request.content));return httpx.Response(status,json={'error':{'code':code}})
            model=await self.model(handler)
            with self.assertRaises(VoiceFault) as caught:await model.complete('synthetic',{})
            self.assertEqual(caught.exception.code,'quota' if 'quota' in code.lower() else 'voice')
            self.assertEqual([c['model'] for c in calls],[OMNI_TEXT_MODEL])
            self.assertIsNone(model.metrics()['cost']['monetary'])
        calls=[]
        def network(request):calls.append(request);raise httpx.ConnectError('SYNTHETIC',request=request)
        model=await self.model(network)
        with self.assertRaises(VoiceFault) as caught:await model.complete('synthetic',{})
        self.assertEqual(caught.exception.code,'network');self.assertEqual(len(calls),1)
    async def test_truncated_tool_refusal_and_nontext_are_not_accepted(self):
        for choice in ({'finish_reason':'length','message':{'content':'{}'}},
                       {'message':{'content':'{}'}},
                       {'finish_reason':'tool_calls','message':{'content':'{}'}},
                       {'finish_reason':'stop','message':{'content':'{}','tool_calls':[{}]}},
                       {'finish_reason':'stop','message':{'content':'{}','refusal':'SYNTHETIC'}},
                       {'finish_reason':'stop','message':{'content':[{'text':'{}'}]}},
                       {'finish_reason':'stop','message':{'content':''}}):
            calls=[]
            def handler(request):calls.append(request);return httpx.Response(200,json={'choices':[choice]})
            model=await self.model(handler)
            with self.assertRaises(ModelError):await model.complete('synthetic',{})
            self.assertEqual(len(calls),1)

    async def test_fact_provenance_cannot_be_rewritten_or_forged(self):
        for value in ('我不喜欢猫','孩子不喜欢猫','PRIVATE_FORGED',[],123):
            def handler(request):
                return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{
                    'content':json.dumps({'facts':[{'key':'preference','value':value}]})}}]})
            model=await self.model(handler)
            bundle=UnifiedProviders(object(),model)
            # The only true source is a negative proposition; a substring that
            # drops negation is not made a positive fact by this adapter.
            if value=='我不喜欢猫':
                facts=await bundle.facts('我不喜欢猫')
                self.assertEqual(facts[0]['start'],0)
                self.assertEqual(facts[0]['value'],'我不喜欢猫')
                # Source is retained for downstream semantic interpretation;
                # lexical containment alone does not certify correct extraction.
            else:
                with self.assertRaises(ModelError):await bundle.facts('我不喜欢猫')
