"""Explicit grammar and actual delivery controls; no cloud semantic claims."""
import unittest
from backend.v2.story_rules import explicit_count,sentence_count,turn_limit
from backend.v2.companion import ModelError
from tests.v2 import test_story_turn_rule as story
from scripts.v2_multiturn_probe import run_case

class Boundaries(unittest.IsolatedAsyncioTestCase):
    async def exercise(self,text,sentences,rule,action='continue'):
        case={'id':'grammar','turns':[{'label':str(i),'input':text,'expect':{'mode':'story','terms':[]}} for i in range(3)]}
        return await run_case(case,story.StoryTurn().providers(sentences,rule,action))

    async def test_equivalent_explicit_counts_gate_actual_voicepeer(self):
        for rule in ('每人说一句','每人只讲一句话','每次讲1句','每轮只说一句','一人一句','你一句我一句'):
            with self.subTest(rule=rule):
                result=await self.exercise('编故事，'+rule,['猫出发。','星星亮了。'],rule)
                self.assertEqual(result['tts_requests'],0)
                self.assertFalse(result['turns'][0]['delivery_metadata']['game_committed'])

    async def test_negated_or_quoted_old_rule_does_not_override_new_rule(self):
        for text in ('不要再一人一句了，改成每人两句。','不是每人一句，而是每人讲两句。','刚才说“一人一句”，改成每人两句。'):
            with self.subTest(text=text):
                result=await self.exercise(text,['猫出发。','飞船升空。'],'每人两句','change')
                self.assertTrue(all(t['checks']['delivery'] for t in result['turns']))
                self.assertEqual(result['tts_requests'],6)
        self.assertEqual(explicit_count('不要再一人一句。'),(True,None))
        self.assertEqual(explicit_count('引用“一人一句”不是当前规则。'),(False,None))

    async def test_current_rule_and_inherited_rule_precedence_without_truncation(self):
        context={'game':{'rules':'每人一句'}}
        p=story.StoryTurn().providers(['猫出发。','飞船升空。'],'每人两句','change')
        self.assertEqual(len((await p.plan('改成每人两句。',context))['sentences']),2)
        with self.assertRaises(ModelError):await p.plan('改成每人一句。',context)
        p.model.next_plan['action']='continue'
        with self.assertRaises(ModelError):await p.plan('接着讲。',context)
        self.assertEqual(context,{'game':{'rules':'每人一句'}})

    async def test_ascii_period_cjk_question_exclamation_and_quotes_block_multiple_sentences(self):
        for output in ('猫出发. 飞船升空.','Cat left. The ship rose.','“猫出发。”飞船升空。','猫出发！飞船升空？'):
            with self.subTest(output=output):
                result=await self.exercise('我们每人说一句。',[output],'每人说一句')
                self.assertEqual(result['tts_requests'],0)
                self.assertFalse(result['turns'][0]['checks']['delivery'])

    async def test_decimal_abbreviations_and_ellipsis_remain_one_contribution(self):
        for output in ('飞船慢慢前进了1.5米。','Dr. Cat slowly boards the ship.','Mr. Cat visits the U.S. station.','猫想了想...才慢慢出发。','猫想了想……才慢慢出发。'):
            with self.subTest(output=output):
                self.assertEqual(sentence_count(output),1)
                result=await self.exercise('我们每人说一句。',[output],'每人说一句')
                self.assertTrue(all(t['checks']['delivery'] for t in result['turns']))
        self.assertEqual(sentence_count('前进1.5米. 飞船停下.'),2)
        self.assertEqual(sentence_count('Dr. Cat boards. The ship rises.'),2)

    async def test_two_sentence_limit_is_not_an_unbounded_bypass(self):
        result=await self.exercise('不要再一人一句，改成每人两句。',['猫出发。','飞船升空。','看见星星。'],'每人两句','change')
        self.assertEqual(result['tts_requests'],0)
        self.assertFalse(result['turns'][0]['delivery_metadata']['game_committed'])
