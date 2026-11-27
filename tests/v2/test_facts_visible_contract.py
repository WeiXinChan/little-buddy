"""Actual Flash HTTP payload and VoicePeer contract boundaries, synthetic only."""
import json
import unittest
import httpx
from backend.dashscope import DashScope
from backend.v2.companion import UnifiedProviders,DashScopeModel,ModelError
from backend.v2 import schemas
from backend.v2.diagnostics import contract_code
from scripts.v2_multiturn_probe import run_case
from tests.v2 import test_m05 as fixtures

TEXT='猜水果吧，你问我答，每次一条线索。'
class VisibleContract(unittest.IsolatedAsyncioTestCase):
    async def make(self,facts,model='deepseek-v4.1-flash-1017'):
        calls=[]
        async def response(request):
            body=json.loads(request.content);calls.append(body);instruction=body['messages'][0]['content']
            result=facts if '提取孩子' in instruction else {'allow':True,'quality':True} if '审核下一个' in instruction else fixtures.plan()
            return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(result,ensure_ascii=False)}}],'usage':{'prompt_tokens':10,'completion_tokens':2}})
        http=httpx.AsyncClient(transport=httpx.MockTransport(response));self.addAsyncCleanup(http.aclose)
        adapter=DashScopeModel(DashScope(http,workspace='synthetic',region='cn-beijing',key='SYNTHETIC',asr='fake',llm=model,tts='fake',voice='fake'))
        return UnifiedProviders(fixtures.Speech(),adapter),calls,adapter

    async def test_actual_flash_request_has_single_key_example_and_canonical_visible_schema(self):
        p,calls,_=await self.make({'facts':[{'key':'rule','value':'每次一条线索'}]})
        facts=await p.facts(TEXT);request=calls[0];instruction=request['messages'][0]['content']
        self.assertIn('输出契约JSON Schema：',instruction)
        visible=json.loads(instruction.split('输出契约JSON Schema：',1)[1])
        self.assertEqual(visible,schemas.FACTS)
        self.assertIn('"key":"rule"',instruction)
        self.assertNotIn('nickname|preference',instruction)
        self.assertEqual(json.loads(request['messages'][1]['content']),{'text':TEXT})
        self.assertEqual(request['response_format'],{'type':'json_object'})
        self.assertFalse(request['enable_thinking']);self.assertEqual(request['max_tokens'],1400)
        self.assertEqual(request['model'],'deepseek-v4.1-flash-1017')
        self.assertEqual(facts[0]['dimension'],'unspecified')

    async def test_invalid_enum_pipeline_hashable_type_unhashable_type_and_source_fail_closed(self):
        cases=[('game_rule','每次一条线索','fact_key'),
               ('nickname|preference|role|rule|clue|plot|promise','每次一条线索','fact_key'),
               (7,'每次一条线索','fact_key'),([], '每次一条线索','fact_key_type'),
               ('rule','FORGED_SUPPLIER_CANARY','fact_source_mismatch')]
        for key,value,reason in cases:
            with self.subTest(reason=reason,key=key):
                p,calls,adapter=await self.make({'facts':[{'key':'rule','value':'每次一条线索'},{'key':key,'value':value}]})
                case={'id':'facts-key-fixture','turns':[{'label':str(i),'input':TEXT,'expect':{'mode':'chat','terms':[]}} for i in range(3)]};snapshots=[]
                report=await run_case(case,p,observer=lambda label,s:snapshots.append(s))
                self.assertEqual(report['peer_failure']['stage'],'facts');self.assertEqual(report['peer_failure']['contract'],reason)
                self.assertEqual(report['model_requests'],2);self.assertEqual(report['tts_requests'],0)
                self.assertEqual(len([c for c in calls if '提取孩子' in c['messages'][0]['content']]),1)
                self.assertEqual(dict(snapshots[0]['facts']),{});self.assertEqual(snapshots[0]['heard'],())
                self.assertFalse(report['turns'][0]['delivery_metadata']['game_committed'])
                self.assertEqual(adapter.metrics()['usage']['requests'],2)
                self.assertNotIn(TEXT,json.dumps(report,ensure_ascii=False));self.assertNotIn('FORGED_SUPPLIER_CANARY',json.dumps(report))

    async def test_valid_explicit_enum_and_source_keep_exact_spans_and_atomic_return(self):
        p,_,_=await self.make({'facts':[{'key':'rule','value':TEXT,'dimension':'unspecified'}]})
        fact=(await p.facts(TEXT))[0]
        self.assertEqual((fact['start'],fact['end']),(0,len(TEXT)));self.assertEqual(fact['value'],TEXT)
        p,_,_=await self.make({'facts':[]});self.assertEqual(await p.facts(TEXT),[])
        p,_,_=await self.make({'facts':[{'key':'rule','value':'每次一条线索','dimension':[]} ]})
        with self.assertRaises(TypeError) as caught:await p.facts(TEXT)
        self.assertEqual(contract_code(caught.exception),'fact_dimension_type')

    async def test_explicit_schema_model_still_gets_same_contract_without_flash_schema_claim(self):
        p,calls,_=await self.make({'facts':[]},model='qwen4-max');await p.facts(TEXT)
        request=calls[0]
        self.assertEqual(request['response_format']['type'],'json_schema')
        self.assertEqual(request['response_format']['json_schema']['schema'],schemas.FACTS)
        instruction=request['messages'][0]['content']
        self.assertEqual(json.loads(instruction.split('输出契约JSON Schema：',1)[1]),schemas.FACTS)
