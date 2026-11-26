"""Synthetic actual VoicePeer, not a claim of live story quality."""
from copy import deepcopy
import unittest
from backend.v2.companion import UnifiedProviders, ModelError
from tests.v2.test_m05 import Model, Speech, plan
from scripts.v2_multiturn_probe import run_case

class StoryTurn(unittest.IsolatedAsyncioTestCase):
    def providers(self,sentences,rules='一人一句，轮流编故事',action='continue'):
        value=plan();value.update(mode='story',rules=rules,roles=['小猫'],sentences=sentences,anchors={},action=action)
        return UnifiedProviders(Speech(),Model(value))

    async def test_actual_voicepeer_multisentence_rule_violation_never_tts_or_commits(self):
        case={'id':'one-sentence','turns':[{'label':str(i),'input':'我们一人一句编故事，小猫坐上飞船。','expect':{'mode':'story','terms':[]}} for i in range(3)]}
        for sentences in (['小猫出发。','它看见星星。','轮到你了。'],['小猫出发。它看见星星。轮到你了。'],['小猫出发！再看哪里？']):
            observations=[]
            report=await run_case(case,self.providers(sentences),observer=lambda label,snapshot:observations.append(snapshot))
            self.assertEqual(report['tts_requests'],0)
            self.assertFalse(report['turns'][0]['checks']['delivery'])
            self.assertFalse(report['turns'][0]['delivery_metadata']['game_committed'])
            self.assertEqual(dict(observations[0]['game']),{})
            self.assertEqual(observations[0]['heard'],())

    async def test_one_sentence_continues_three_ack_committed_turns(self):
        case={'id':'one-sentence','turns':[{'label':str(i),'input':text,'expect':{'mode':'story','terms':['一句']}} for i,text in enumerate(('我们一人一句编故事。','小猫看到蓝色星星，你接。','飞船只能慢慢飞，不许传送。'))]}
        snapshots=[]
        report=await run_case(case,self.providers(['小猫慢慢飞向蓝色星星。']),observer=lambda label,snapshot:snapshots.append(snapshot))
        self.assertEqual(len(report['turns']),3)
        self.assertTrue(all(t['checks']['delivery'] and t['delivery_metadata']['game_committed'] for t in report['turns']))
        self.assertTrue(all(s['heard'] for s in snapshots))

    async def test_existing_rule_cannot_be_silently_removed_on_continuation(self):
        p=self.providers(['小猫出发。','轮到你了。'],rules='继续故事')
        context={'game':{'mode':'story','rules':'每次只讲一句话'}};before=deepcopy(context)
        with self.assertRaises(ModelError):await p.plan('继续。',context)
        self.assertEqual(context,before)

    async def test_explicit_new_rule_and_leave_do_not_inherit_old_sentence_limit(self):
        p=self.providers(['小猫出发。','蓝星出现。'],rules='每次两句',action='change')
        result=await p.plan('改规则，每次两句。',{'game':{'rules':'一人一句'}})
        self.assertEqual(len(result['sentences']),2) # no truncation
        p.model.next_plan.update(mode='chat',action='leave')
        self.assertEqual((await p.plan('不玩了，聊聊。',{'game':{'rules':'一人一句'}}))['action'],'leave')
