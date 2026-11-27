import unittest,json
from unittest.mock import patch
from scripts import v2_guess_confirm as g
from scripts import v2_multiturn_probe as probe
from tests.v2 import test_m05 as old
from backend.v2.companion import UnifiedProviders

class Model(old.Model):
    def __init__(self,answer='风筝'):
        super().__init__(old.plan());self.answer=answer;self.inputs=[]
    async def complete(self,instruction,data,*,schema=None):
        if '严格字段' in instruction:
            self.inputs.append(data['text'])
            count=len(self.inputs)
            self.next_plan.update(action='change' if count in (1,3) else 'continue',mode='guess',
                rules='瓦力出题孩子猜' if count<3 else '孩子出题瓦力猜',roles=['瓦力出题','孩子猜'] if count<3 else ['孩子出题','瓦力猜'],
                secrets={'answer':self.answer} if self.answer and count<3 else {},
                sentences=['它可以飞起来。'] if count==1 else [f'猜对了，是{self.answer}。'] if count==2 else ['我猜是灯。'])
        return await super().complete(instruction,data,schema=schema)

class Confirm(unittest.IsolatedAsyncioTestCase):
    async def test_actual_current_session_answer_constructs_only_second_input(self):
        for answer in ('风筝','气球'):
            m=Model(answer);result=await g.run_group(UnifiedProviders(old.Speech(),m));g.validate_result(result)
            turns=result['cases'][0]['turns']
            self.assertEqual(m.inputs[1],'是'+answer+'吗？提示它有什么用。')
            self.assertTrue(turns[1]['dynamic_synthetic_guess']);self.assertEqual(turns[1]['synthetic_input'],m.inputs[1])
            self.assertEqual(turns[0]['synthetic_hidden_after'],{'answer':answer})
            self.assertEqual(turns[2]['synthetic_hidden_after'],{})
            self.assertIsNone(result['semantic_pass'])
    async def test_missing_answer_stops_before_second_request(self):
        m=Model(None);result=await g.run_group(UnifiedProviders(old.Speech(),m))
        self.assertEqual(len(m.inputs),1);self.assertTrue(result['stopped'])
        self.assertEqual(result['cases'][0]['dynamic_guess_failure'],'dynamic_guess_missing_answer')
        self.assertEqual(len(result['cases'][0]['turns']),1)
    async def test_no_ack_does_not_construct_second_turn(self):
        class NoAck(probe.Sink):
            def __init__(self,*args):super().__init__(False)
        m=Model()
        with patch.object(probe,'Sink',NoAck),patch.dict(g.LIMITS,execution_seconds=.05):
            result=await g.run_group(UnifiedProviders(old.Speech(),m))
        self.assertEqual(len(m.inputs),1);self.assertEqual(len(result['cases'][0]['turns']),1)
        self.assertTrue(result['stopped']);self.assertFalse(result['cases'][0]['turns'][0]['reply_final_segment_ack'])
    async def test_source_pin_and_default_disabled(self):
        self.assertEqual(g.SOURCE,'a3ed0ea2b42bb3a341cecc7e27f6d71d14e0ede9')
        self.assertEqual(len(g.verify_source()),64)
        with patch.object(g,'verify_source',side_effect=AssertionError('no read')):
            self.assertEqual(g.main(['--case','guess-confirm']),0)
            self.assertEqual(g.main(['--case','guess-confirm','--execute']),2)
        with self.assertRaises(ValueError):g.select_case('guess-object')
