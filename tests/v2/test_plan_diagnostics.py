"""PLAN branch diagnostics only; no live-story or repair success claim."""
from copy import deepcopy
import json
import unittest
from backend.v2.companion import UnifiedProviders,ModelError
from backend.v2.diagnostics import contract_code
from tests.v2 import test_m05 as fixtures
from scripts.v2_multiturn_probe import run_case

class PlanDiagnostics(unittest.IsolatedAsyncioTestCase):
    async def test_all_local_plan_validation_groups_have_content_free_codes(self):
        base=fixtures.plan();base.update(anchors={},tools=[])
        cases=[('extra','SECRET','plan_structure'),('action','bad','plan_action'),('mode','bad','plan_mode'),
               ('rules',[],'plan_rules'),('roles',['x'*81],'plan_roles'),('secrets',{'x':3},'plan_secrets'),
               ('sentences',[],'plan_sentences'),('sentences',['x'*121],'plan_sentences'),
               ('anchors',{'plot.main':True},'plan_anchors'),('anchors',{'plot.main':4},'plan_anchors'),
               ('tools',[{'kind':'bad'}],'plan_tool_schema'),('tools',[{'kind':'show_image','description':{}}],'plan_tool_schema')]
        for field,value,expected in cases:
            with self.subTest(field=field,value=value):
                proposal=deepcopy(base);proposal[field]=value
                with self.assertRaises(ModelError) as caught:await UnifiedProviders(fixtures.Speech(),fixtures.Model(proposal)).plan('合成输入',{})
                self.assertEqual(contract_code(caught.exception),expected)
                self.assertNotIn('SECRET',contract_code(caught.exception))

    async def test_unhashable_enum_still_typeerror_and_unknown_messages_are_not_exported(self):
        for field,expected in [('action','plan_action'),('mode','plan_mode')]:
            proposal=fixtures.plan();proposal[field]=[]
            with self.assertRaises(TypeError) as caught:await UnifiedProviders(fixtures.Speech(),fixtures.Model(proposal)).plan('合成',{})
            self.assertEqual(contract_code(caught.exception),expected)
        self.assertEqual(contract_code(ModelError('SIGNED_URL_CANARY')),'unknown')
        # PR97's unchanged literal failure label composes with this constructor;
        # this is NOT a re-execution of the PR97 count gate on this PR99 base.
        self.assertEqual(contract_code(ModelError('story turn sentence limit')),'plan_sentence_limit')

    async def test_second_turn_failure_keeps_first_ack_state_no_extra_retry_or_tts(self):
        class Model(fixtures.Model):
            async def complete(self,instruction,data,*,schema=None):
                if '严格字段' in instruction:
                    self.next_plan=fixtures.plan();self.next_plan.update(mode='story',rules='轮流编故事')
                    if data['text']=='第二轮':self.next_plan['anchors']={'plot.main':99}
                return await super().complete(instruction,data,schema=schema)
        model=Model(fixtures.plan());seen=[]
        case={'id':'plan-fail','turns':[{'label':str(i),'input':text,'expect':{'mode':'story','terms':[]}} for i,text in enumerate(('第一轮','第二轮','第三轮'))]}
        report=await run_case(case,UnifiedProviders(fixtures.Speech(),model),observer=lambda label,snapshot:seen.append(snapshot))
        self.assertEqual(len(report['turns']),2);self.assertEqual(report['tts_requests'],1)
        self.assertEqual(report['peer_failure'],{'stage':'plan','kind':'ModelError','contract':'plan_structure'})
        self.assertEqual(report['turns'][1]['plan_format_repair'],{'initial_detail':'anchor_index_range','encoding':'sentence_labels','validated':False})
        self.assertEqual(report['turns'][1]['delivery_metadata']['audio_chunks'],0)
        self.assertFalse(report['turns'][1]['delivery_metadata']['game_committed'])
        self.assertEqual(seen[0]['heard'],seen[1]['heard']);self.assertEqual(seen[0]['game'],seen[1]['game'])
        # The approved format repair spends the one shared slot; still no
        # third generation, TTS, or state on the second bad candidate.
        self.assertEqual(len([i for i,d in model.requests if '严格字段' in i]),3)
        self.assertNotIn('第二轮',json.dumps(report,ensure_ascii=False))

    async def test_optional_defaults_and_valid_plan_still_follow_original_contract(self):
        proposal=fixtures.plan();p=UnifiedProviders(fixtures.Speech(),fixtures.Model(proposal))
        result=await p.plan('合成',{})
        self.assertEqual(result['sentences'],proposal['sentences'])
        self.assertEqual(result['anchors'],{});self.assertEqual(result['tools'],[])
