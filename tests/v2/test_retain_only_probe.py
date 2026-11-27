import unittest,json
from unittest.mock import patch
from backend.v2.companion import UnifiedProviders
from tests.v2 import test_m05 as old
from scripts import v2_retain_only_probe as probe

class Model(old.Model):
    def __init__(self):super().__init__(old.plan());self.inputs=[]
    async def complete(self,instruction,data,*,schema=None):
        if '严格字段' in instruction:
            self.inputs.append(data['text'])
            self.next_plan.update(action='change' if len(self.inputs)==1 else 'continue',mode='association',rules='会飞的东西，不重复'+('，两个字' if len(self.inputs)==2 else ''),sentences=['我说风筝。'] if len(self.inputs)==1 else ['我说雄鹰。'])
        return await super().complete(instruction,data,schema=schema)

class Preparation(unittest.IsolatedAsyncioTestCase):
    async def test_two_inputs_same_session_actual_ack_state_and_usage(self):
        m=Model();r=await probe.run_group(UnifiedProviders(old.Speech(),m));probe.validate_result(r)
        self.assertEqual(m.inputs,list(probe.TURNS['retain-only-change']))
        self.assertEqual(len(r['cases']),1);self.assertEqual(len(r['cases'][0]['turns']),2)
        a,b=r['cases'][0]['turns']
        self.assertTrue(a['reply_final_segment_ack'] and b['reply_final_segment_ack'])
        self.assertEqual(b['game_before'],a['game_after'])
        self.assertEqual(b['actual_complete_ack_texts'],['我说雄鹰。'])
        self.assertIn('两个字',b['game_after']['rules'])
        self.assertIsNone(r['semantic_pass']);self.assertTrue(r['cleanup_confirmed'])
        self.assertIn('usage',r)
    async def test_failed_first_reply_stops_before_second_input(self):
        m=Model();m.allowed=False
        r=await probe.run_group(UnifiedProviders(old.Speech(),m))
        self.assertTrue(r['stopped']);self.assertEqual(len(m.inputs),1)
        self.assertEqual(len(r['cases'][0]['turns']),1)
        self.assertEqual(r['cases'][0]['turns'][0]['actual_complete_ack_texts'],[])
        with self.assertRaises(ValueError):probe.validate_result(r)
    async def test_total_model_limit_is_sixteen_and_no_fallback(self):
        g=probe.Guard();m=old.Model(old.plan());meter=probe.Meter(m,g)
        for _ in range(16):g.turn_stages={};await meter.complete('synthetic',{},schema={})
        g.turn_stages={}
        with self.assertRaises(RuntimeError):await meter.complete('synthetic',{},schema={})
        self.assertEqual(len(m.requests),16);self.assertEqual(g.denials[-1]['reason'],'model_requests')
        self.assertEqual(probe.LIMITS['model_requests'],16)
        self.assertTrue(probe.admission()['no_fallback'])
    async def test_only_single_case_no_all_memory_or_default_execution(self):
        for name in ('all','memory-compare','explicit-new-round','guess-object'):
            with self.assertRaises(ValueError):probe.select_case(name)
        with patch.object(probe,'verify_source',side_effect=AssertionError('no config/network')):
            self.assertEqual(probe.main(['--case','retain-only-change']),0)
            self.assertEqual(probe.main(['--case','retain-only-change','--execute']),2)
        with self.assertRaises(SystemExit):probe.main(['--case','all'])
    async def test_source_pin_matches_fixed_production_not_tool_self_hash(self):
        self.assertEqual(probe.SOURCE,'253ad055a87ca21103e3c95b729874aaeaa7ce28')
        self.assertEqual(len(probe.verify_source()),64)
        from pathlib import Path
        pin=json.loads((Path(probe.__file__).parent/'v2_retain_only_probe_pin.json').read_text())
        self.assertNotIn('scripts/v2_retain_only_probe.py',pin['files'])
        self.assertNotIn('scripts/v2_retain_only_probe_pin.json',pin['files'])
    async def test_production_single_format_repair_is_admitted_within_same_cap(self):
        from tests.v2.test_plan_format_repair import FormatModel
        class Association(FormatModel):
            async def complete(self,instruction,data,*,schema=None):
                raw=await super().complete(instruction,data,schema=schema)
                if '严格字段' in instruction:
                    value=json.loads(raw);value.update(mode='association',rules='会飞，不重复');return json.dumps(value,ensure_ascii=False)
                return raw
        m=Association();r=await probe.run_group(UnifiedProviders(old.Speech(),m));probe.validate_result(r)
        self.assertEqual(m.calls,3);self.assertEqual(m.facts,2)
        self.assertEqual(len(r['cases'][0]['turns']),2)
        self.assertEqual(r['totals']['budget_denials'],[])
        self.assertLessEqual(r['totals']['model_requests'],16)
