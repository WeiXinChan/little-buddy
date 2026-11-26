"""Synthetic malformed contracts; no supplier body logged by diagnostics."""
import asyncio
import json
import unittest
import httpx
from backend.dashscope import DashScope
from backend.v2.companion import UnifiedProviders,DashScopeModel,object_json,ModelError
from backend.v2.diagnostics import contract_code
from scripts.v2_multiturn_probe import run_case,peer_failure
from tests.v2 import test_m05 as fixtures

class RawModel(fixtures.Model):
    def __init__(self,raw):super().__init__(fixtures.plan());self.raw=raw
    async def complete(self,instruction,data,*,schema=None):
        if '提取孩子' in instruction:
            self.requests.append((instruction,data));return self.raw
        return await super().complete(instruction,data,schema=schema)

class Diagnostics(unittest.IsolatedAsyncioTestCase):
    async def failure(self,raw,text='合成原文'):
        p=UnifiedProviders(fixtures.Speech(),RawModel(raw))
        try:await p.facts(text)
        except Exception as error:return type(error),str(error),contract_code(error)
        self.fail('invalid contract accepted')

    async def test_structure_type_count_and_source_are_distinct_without_relaxing_contract(self):
        cases=[({},'facts_structure'),({'facts':{}},'facts_list_type'),({'facts':[{}]*9},'facts_count'),
               ({'facts':[{}]},'fact_structure'),({'facts':[{'key':'bad','value':'合成原文'}]},'fact_key'),
               ({'facts':[{'key':'rule','value':1}]},'fact_value_type'),
               ({'facts':[{'key':'rule','value':''}]},'fact_value_length'),
               ({'facts':[{'key':'rule','value':'供应商私密CANARY'}]},'fact_source_mismatch'),
               ({'facts':[{'key':'rule','value':'合成原文','dimension':'bad'}]},'fact_dimension')]
        for raw,code in cases:
            with self.subTest(code=code):
                kind,message,diagnostic=await self.failure(json.dumps(raw))
                self.assertIs(kind,ModelError);self.assertEqual(diagnostic,code)
                self.assertIn(message,{'facts','fact provenance','fact dimension'})

    async def test_unhashable_types_preserve_original_typeerror_not_blanket_modelerror(self):
        for field,code in [('key','fact_key_type'),('dimension','fact_dimension_type')]:
            fact={'key':'rule','value':'合成原文',field:[]}
            kind,_,reason=await self.failure(json.dumps({'facts':[fact]}))
            self.assertIs(kind,TypeError);self.assertEqual(reason,code)

    async def test_json_parse_failures_keep_original_classes_and_safe_codes(self):
        for raw,kind,code in [([],ModelError,'json_type'),('x'*24001,ModelError,'json_capacity'),
                              ('{"facts":[],"facts":[]}',ModelError,'json_duplicate'),
                              ('{CANARY',json.JSONDecodeError,'json_syntax')]:
            with self.subTest(code=code):
                actual,_,diagnostic=await self.failure(raw)
                self.assertIs(actual,kind);self.assertEqual(diagnostic,code)
        with self.assertRaises(UnicodeEncodeError) as caught:object_json('\ud800')
        self.assertEqual(contract_code(caught.exception),'json_encoding')

    async def test_accepted_sources_keep_exact_spans_dimensions_and_no_partial_return(self):
        text='我不喜欢猫，我喜欢狗。'
        raw=json.dumps({'facts':[{'key':'preference','value':text},{'key':'rule','value':'喜欢狗','dimension':'animal'}]})
        facts=await UnifiedProviders(fixtures.Speech(),RawModel(raw)).facts(text)
        for fact in facts:self.assertEqual(text[fact['start']:fact['end']],fact['value'])
        self.assertEqual(facts[0]['dimension'],'unspecified')
        self.assertEqual(await UnifiedProviders(fixtures.Speech(),RawModel('{"facts":[]}')).facts(text),[])
        self.assertEqual(await UnifiedProviders(fixtures.Speech(),RawModel('not called')).facts(None),[])
        raw=json.dumps({'facts':[{'key':'rule','value':'我不喜欢猫'},{'key':'rule','value':'FORGED'}]})
        self.assertEqual((await self.failure(raw,text))[2],'fact_source_mismatch')

    async def test_actual_peer_reports_fixed_code_zero_tts_no_retry_or_commit_no_body(self):
        model=RawModel('{"facts":[{"key":"rule","value":"PRIVATE_CANARY"}]}')
        p=UnifiedProviders(fixtures.Speech(),model);seen=[]
        case={'id':'facts-invalid','turns':[{'label':str(i),'input':'合成原文','expect':{'mode':'chat','terms':[]}} for i in range(3)]}
        report=await run_case(case,p,observer=lambda label,s:seen.append(s))
        self.assertEqual(report['peer_failure'],{'stage':'facts','kind':'ModelError','contract':'fact_source_mismatch'})
        self.assertEqual(report['tts_requests'],0);self.assertEqual(report['model_requests'],2)
        self.assertEqual(len([i for i,d in model.requests if '提取孩子' in i]),1)
        self.assertFalse(report['turns'][0]['delivery_metadata']['game_committed'])
        self.assertEqual(seen[0]['heard'],());self.assertEqual(dict(seen[0]['game']),{})
        self.assertNotIn('PRIVATE_CANARY',json.dumps(report));self.assertNotIn('合成原文',json.dumps(report))

    async def test_upstream_envelope_parse_stages_preserve_model_unavailable(self):
        cases=[(b'x'*64001,'upstream_capacity'),(b'{PRIVATE','upstream_json'),(b'{}','upstream_structure')]
        for body,expected in cases:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=body))) as http:
                m=DashScopeModel(DashScope(http,workspace='synthetic',region='cn-beijing',key='SYNTHETIC',asr='fake',llm='deepseek-v4.1-flash-1017',tts='fake',voice='fake'))
                with self.assertRaisesRegex(ModelError,'^model unavailable$') as caught:await m.complete('synthetic',{})
                self.assertEqual(contract_code(caught.exception),expected)

    async def test_unknown_or_forged_diagnostic_never_serializes_arbitrary_text(self):
        class Peer:pass
        peer=Peer();peer.last_failure={'stage':'facts','kind':'ModelError','contract':'SECRET'}
        self.assertEqual(peer_failure(peer)['contract'],'unknown')
        error=ValueError('secret');error.contract_diagnostic=[]
        self.assertEqual(contract_code(error),'unknown')
