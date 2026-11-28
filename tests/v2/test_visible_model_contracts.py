"""Actual HTTP and VoicePeer gates, not live model semantic certification."""
from copy import deepcopy
import asyncio
import json
import unittest
import httpx
from backend.dashscope import DashScope
from backend.v2.companion import UnifiedProviders,DashScopeModel,ModelError
from backend.v2 import schemas
from backend.v2.diagnostics import contract_code,contract_detail
from scripts.v2_multiturn_probe import run_case,peer_failure
from tests.v2 import test_m05 as fixtures

class Contracts(unittest.IsolatedAsyncioTestCase):
    model_name='deepseek-v4.1-flash-1017'
    async def make(self,proposal=None,allow=True,wait_facts=False):
        facts_ready=asyncio.Event()
        calls=[];proposal=deepcopy(proposal or fixtures.plan())
        async def response(request):
            body=json.loads(request.content);calls.append(body);instruction=body['messages'][0]['content']
            if '提取孩子' in instruction:facts_ready.set()
            elif wait_facts and '严格字段' in instruction:await facts_ready.wait()
            value=({'facts':[]} if '提取孩子' in instruction else {'allow':allow,'quality':True} if '审核下一个' in instruction else
                   {'keep':[]} if '只返回JSON {"keep"' in instruction else
                   {'completion':'complete','meaning':'new_turn'} if 'completion:' in instruction else proposal)
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value,ensure_ascii=False)}}],
                                          'usage':{'prompt_tokens':10,'completion_tokens':2}})
        http=httpx.AsyncClient(transport=httpx.MockTransport(response));self.addAsyncCleanup(http.aclose)
        model=DashScopeModel(DashScope(http,workspace='synthetic',region='cn-beijing',key='SYNTHETIC',asr='fake',llm=self.model_name,tts='fake',voice='fake'))
        return UnifiedProviders(fixtures.Speech(),model),calls

    async def test_every_json_object_stage_sees_canonical_schema_once_and_single_value_examples(self):
        p,calls=await self.make()
        await p.endpoint('合成输入',{});await p.plan('合成输入',{});await p.facts('合成输入');await p.safe('合成回应',{});await p.compact([])
        self.assertEqual(len(calls),5)
        for body,schema in zip(calls,(schemas.ENDPOINT,schemas.PLAN,schemas.FACTS,schemas.REVIEW,schemas.COMPACT)):
            instruction=body['messages'][0]['content']
            self.assertEqual(instruction.count('输出契约JSON Schema：'),1)
            self.assertEqual(json.loads(instruction.split('输出契约JSON Schema：',1)[1]),schema)
            self.assertEqual(body['response_format'],{'type':'json_object'})
            if self.model_name=='qwen3.8-omni-flash':
                self.assertEqual(body['reasoning_effort'],'none');self.assertEqual(body['modalities'],['text'])
                self.assertNotIn('enable_thinking',body)
            else:self.assertFalse(body['enable_thinking'])
            self.assertEqual(body['max_tokens'],1400)
        instruction=calls[1]['messages'][0]['content']
        self.assertIn('下标从0开始',instruction);self.assertIn('实际len(sentences)',instruction)
        self.assertIn('不创建answer.current',instruction);self.assertNotIn('continue|change',instruction)
        self.assertNotIn('show_image|hide_image',instruction)

    async def test_anchor_structure_type_and_actual_length_bounds_block_before_playback(self):
        cases=[([], 'anchors_container'),({str(i):0 for i in range(17)},'anchors_count'),
               ({'':0},'anchor_name'),({'x'*41:0},'anchor_name'),({'clue.current':True},'anchor_index_type'),
               ({'clue.current':'0'},'anchor_index_type'),({'clue.current':.0},'anchor_index_type'),
               ({'clue.current':-1},'anchor_index_range'),({'clue.current':1},'anchor_index_range'),
               ({'clue.current':3},'anchor_index_range')]
        for anchors,detail in cases:
            with self.subTest(detail=detail,anchors=anchors):
                value=fixtures.plan();value.update(mode='guess',secrets={'answer':'UNREVEALED_CANARY'},anchors=anchors)
                p,calls=await self.make(value,wait_facts=True);seen=[]
                case={'id':'anchors-fixture','turns':[{'label':str(i),'input':'你出动物谜语我猜，不要先说答案。','expect':{'mode':'guess','terms':[]}} for i in range(3)]}
                report=await run_case(case,p,observer=lambda label,s:seen.append(s))
                repairable=detail in ('anchor_index_type','anchor_index_range')
                expected={'stage':'plan','kind':'ModelError','contract':'plan_structure'} if repairable else {'stage':'plan','kind':'ModelError','contract':'plan_anchors','detail':detail}
                self.assertEqual(report['peer_failure'],expected)
                if repairable:self.assertEqual(report['turns'][0]['plan_format_repair'],dict(initial_detail=detail,encoding='sentence_labels',validated=False))
                self.assertEqual(report['tts_requests'],0)
                repairable=detail in ('anchor_index_type','anchor_index_range')
                self.assertEqual(report['model_requests'],3 if repairable else 2)
                self.assertEqual(seen[0]['heard'],());self.assertEqual(dict(seen[0]['game']),{})
                self.assertFalse(report['turns'][0]['delivery_metadata']['game_committed'])
                self.assertNotIn('UNREVEALED_CANARY',json.dumps(report))
                self.assertEqual(len([c for c in calls if '严格字段' in c['messages'][0]['content']]),2 if repairable else 1)

    async def test_last_actual_index_is_valid_and_bounds_are_not_global_capacity(self):
        for sentences,anchors in [(['第一句。'],{'clue.current':0}),(['第一句。','第二句。'],{'plot.main':0,'clue.current':1}),
                                  (['甲。','乙。','丙。','丁。'],{'plot.main':3})]:
            value=fixtures.plan();value.update(sentences=sentences,anchors=anchors)
            p,_=await self.make(value);result=await p.plan('合成输入',{})
            self.assertEqual(result['anchors'],anchors);self.assertEqual(result['sentences'],sentences)
        value=fixtures.plan();value.update(sentences=['第一句。','第二句。'],anchors={'clue.current':2})
        p,_=await self.make(value)
        with self.assertRaises(ModelError) as caught:await p.plan('合成输入',{})
        self.assertEqual(contract_detail(caught.exception),'anchor_index_range')

    async def test_hidden_riddle_commits_answer_only_as_secret_and_clue_only_when_played(self):
        value=fixtures.plan();value.update(mode='guess',rules='每次一条线索',roles=['瓦力出题','孩子猜'],
                                          secrets={'answer':'兔子'},sentences=['它有长长的耳朵。'],anchors={'clue.current':0})
        p,calls=await self.make(value);seen=[]
        case={'id':'hidden-answer','turns':[{'label':str(i),'input':text,'expect':{'mode':'guess','terms':['线索']}} for i,text in enumerate(('你出动物谜语我猜。','是不是猫？','再给我一条线索。'))]}
        report=await run_case(case,p,observer=lambda label,s:seen.append(s))
        self.assertEqual(len(report['turns']),3);self.assertTrue(all(t['checks']['delivery'] for t in report['turns']))
        self.assertTrue(all(s['unrevealed']=={'answer':'兔子'} for s in seen))
        for snapshot in seen:
            self.assertNotIn('兔子',str(snapshot['heard']));self.assertNotIn('兔子',str(snapshot['facts']))
            self.assertNotIn('public:played:answer.current',snapshot['facts'])
            self.assertEqual(snapshot['facts']['public:played:clue.current']['value'],'它有长长的耳朵。')
        self.assertNotIn('兔子',json.dumps(report,ensure_ascii=False))
        self.assertEqual(len([c for c in calls if '严格字段' in c['messages'][0]['content']]),3)

    async def test_secret_continuation_preservation_is_not_anchor_binding_or_new_mismatch_exception(self):
        value=fixtures.plan();value.update(mode='guess',secrets={'answer':'新猜测'},anchors={'clue.current':0})
        p,_=await self.make(value)
        result=await p.plan('是不是另一种动物？',{'unrevealed':{'answer':'原谜底'}})
        self.assertEqual(result['secrets'],{'answer':'原谜底'})
        self.assertEqual(result['anchors'],{'clue.current':0})
        self.assertEqual(contract_detail(ModelError('anchors')),'unknown') # old root report has no recoverable subtype

    async def test_static_key_and_secret_limits_equal_unchanged_local_validation(self):
        self.assertEqual(schemas.PLAN['properties']['anchors']['propertyNames'],{'type':'string','minLength':1,'maxLength':40})
        self.assertEqual(schemas.PLAN['properties']['secrets']['propertyNames']['maxLength'],79)
        self.assertEqual(schemas.PLAN['properties']['secrets']['additionalProperties']['maxLength'],999)
        value=fixtures.plan();value['secrets']={'k'*79:'v'*999}
        p,_=await self.make(value);self.assertEqual((await p.plan('合成输入',{}))['secrets'],value['secrets'])
        for secrets in ({'k'*80:'v'},{'k':'v'*1000}):
            value=fixtures.plan();value['secrets']=secrets;p,_=await self.make(value)
            with self.assertRaises(ModelError) as caught:await p.plan('合成输入',{})
            self.assertEqual(contract_code(caught.exception),'plan_secrets')

    async def test_safety_rejection_still_blocks_correctly_structured_plan_and_diagnostics_are_allowlisted(self):
        value=fixtures.plan();value.update(mode='guess',secrets={'answer':'CANARY'},anchors={'clue.current':0})
        p,_=await self.make(value,allow=False)
        case={'id':'review-reject','turns':[{'label':str(i),'input':'合成请求','expect':{'mode':'guess','terms':[]}} for i in range(3)]}
        report=await run_case(case,p);self.assertEqual(report['tts_requests'],0)
        self.assertFalse(report['turns'][0]['checks']['delivery'])
        class Peer:last_failure={'stage':'plan','kind':'ModelError','contract':'plan_anchors','detail':'SIGNED_URL_CANARY'}
        self.assertEqual(peer_failure(Peer())['detail'],'unknown');self.assertNotIn('SIGNED_URL',json.dumps(peer_failure(Peer())))
