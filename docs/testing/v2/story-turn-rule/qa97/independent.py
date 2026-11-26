import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'source'))
from tests.v2.test_story_turn_rule import StoryTurn
from scripts.v2_multiturn_probe import run_case
class Independent(unittest.IsolatedAsyncioTestCase):
 async def exercise(self,text,sentences,rules,action='continue'):
  case={'id':'independent-story','turns':[{'label':str(i),'input':text,'expect':{'mode':'story','terms':[]}} for i in range(3)]}
  snapshots=[];p=StoryTurn().providers(sentences,rules,action)
  report=await run_case(case,p,observer=lambda label,s:snapshots.append(s))
  return report,snapshots
 async def test_explicit_negation_and_new_two_sentence_rule_must_be_accepted(self):
  report,_=await self.exercise('不要再一人一句了，改成每人两句。',['小猫启动飞船。','飞船慢慢升空。'],'每人两句，轮流编故事','change')
  print('NEGATED_OLD_RULE',report['tts_requests'],report['turns'][0]['checks']['delivery'])
  self.assertTrue(report['turns'][0]['checks']['delivery'],'valid new rule must not inherit negated old limit')
 async def test_natural_explicit_one_sentence_rule_must_block_multiple_sentences(self):
  report,_=await self.exercise('我们轮流编故事，每人说一句。',['小猫启动飞船。','飞船慢慢升空。'],'轮流编故事，每人说一句')
  print('EXPLICIT_VARIANT',report['tts_requests'],report['turns'][0]['delivery_metadata']['game_committed'])
  self.assertEqual(report['tts_requests'],0,'explicit one-sentence rule must gate complete proposal')
 async def test_ascii_sentence_periods_cannot_hide_multiple_sentences(self):
  report,_=await self.exercise('我们一人一句编故事。',['小猫启动飞船. 飞船慢慢升空.'],'一人一句，轮流编故事')
  print('ASCII_PERIODS',report['tts_requests'],report['turns'][0]['delivery_metadata']['game_committed'])
  self.assertEqual(report['tts_requests'],0,'one array entry can still contain multiple complete sentences')
 async def test_unrestricted_story_and_private_transition_remain_accepted(self):
  for text,rules,action in [('我们一起编故事。','轮流编故事','continue'),('我们一人一句的故事先停下，我想聊私事。','一人一句','private')]:
   report,_=await self.exercise(text,['小猫启动飞船。','飞船慢慢升空。'],rules,action)
   self.assertGreater(report['tts_requests'],0)
   self.assertTrue(report['turns'][0]['checks']['delivery'])
if __name__=='__main__':unittest.main(defaultTest='Independent',verbosity=2)
