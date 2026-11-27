"""Combination-head evidence: synthetic providers, real Session/VoicePeer, no cloud."""
import asyncio
import json
import unittest
from dataclasses import replace
from backend.v2.memory import unpack
from backend.v2.session import Session
from tests.v2 import test_m05 as existing

class MemoryBoundaries(unittest.TestCase):
    def test_same_session_cold_sources_and_played_unplayed_after_compaction(self):
        s=Session(lambda:0);identity=s.session
        source='我不喜欢猫玩偶，但我喜欢狗'
        for n in range(90):
            text=source if n==0 else f'我喜欢第{n}种颜色'
            s.record_input(text,[dict(key='preference',value=text,start=0,end=len(text))])
        cold=unpack(s.source_archive)
        self.assertTrue(cold)
        self.assertEqual(len({v['source_id'] for _,v in list(s.facts.items())+list(cold.values())}),90)
        s.begin_turn();s.drain_commands();s.bind_player('synthetic');s.drain_commands()
        t=s.task('tts');a=s.task('ack')
        self.assertTrue(s.send(t,name='played',public='狗船长答应先找蓝色钥匙。',end=240,approved=True,effective=True,anchors=('promise.current',)))
        self.assertTrue(s.ack(a,player='synthetic',stream=s.stream,segment='played',head=240))
        self.assertTrue(s.send(replace(t,sequence=1),name='unplayed',public='UNPLAYED_CANARY',end=480,approved=True,effective=True,anchors=('promise.current',)))
        s.interrupt();s.drain_commands()
        s.public.extend(f'背景{n}' for n in range(50))
        self.assertTrue(s.compact(s.memory_snapshot(),[]))
        context=s.context(query='猫狗')
        self.assertEqual(s.session,identity)
        self.assertIn(source,str(context['facts']))
        self.assertIn('狗船长答应先找蓝色钥匙。',str(context['facts']))
        self.assertNotIn('UNPLAYED_CANARY',str(context))
        self.assertTrue(s._fits())

class WireBoundaries(unittest.IsolatedAsyncioTestCase):
    make=existing.Integration.make
    turn=existing.Integration.turn

    async def test_private_and_hidden_answer_across_modes_and_shared_replan(self):
        self.make();s=self.peer.session
        self.model.next_plan.update(action='private',sentences=['PRIVATE_CANARY。'])
        await self.turn('合成私事')
        self.model.next_plan.update(action='change',mode='guess',rules='轮流提示',secrets={'answer':'HIDDEN_CANARY'},sentences=['它有长耳朵。'])
        await self.turn('回到公开猜谜')
        self.assertIs(self.peer.session,s)
        shared=s.context(shared=True)
        self.assertNotIn('PRIVATE_CANARY',str(shared))
        self.assertNotIn('HIDDEN_CANARY',str(shared))
        self.assertEqual(s.context()['unrevealed'],{'answer':'HIDDEN_CANARY'})
        self.assertNotIn('HIDDEN_CANARY',str(s.context()['heard']))
        self.model.next_plan.update(action='change',mode='story',secrets={},sentences=['蓝色飞船出发。'])
        await self.turn('换成故事')
        self.assertNotIn('PRIVATE_CANARY',str(s.context(shared=True)))
        self.assertEqual(s.secrets,{})
        self.assertNotIn('HIDDEN_CANARY',str(s.context()))
        plans=[d for i,d in self.model.requests if '严格字段' in i]
        # Private-to-shared second PLAN receives the actual public projection.
        shared_replans=[d for d in plans if d['text']=='回到公开猜谜' and not d['context']['private']]
        self.assertTrue(shared_replans)
        self.assertNotIn('PRIVATE_CANARY',str(shared_replans))

    async def test_one_leaves_then_any_speaker_stop_then_all_end(self):
        self.make();s=self.peer.session
        self.model.next_plan.update(action='continue',mode='story',roles=['孩子甲','孩子乙'],sentences=['我们继续蓝星故事。'])
        await self.turn('我先退出，你们继续')
        self.assertIs(self.peer.session,s);self.assertTrue(s.active)
        self.assertEqual(s.game['roles'],['孩子甲','孩子乙'])
        before=list(s.public);old_ack=self.peer.ack_identity
        # Wire stop has no speaker/auth attribution; any input source can stop.
        await self.peer.handle(json.dumps(dict(v=2,type='stop',epoch=self.peer.epoch+1,seq=0,intent='synthetic-any-speaker')))
        self.assertTrue(s.active);self.assertEqual(s.public,before)
        self.assertFalse(s.accept(old_ack));self.assertFalse(s.pending)
        self.model.next_plan.update(action='end',mode='chat',roles=[],rules='',sentences=['再见。'])
        await self.turn('我们都不玩了')
        self.assertFalse(s.active);self.assertEqual(s.context(),{})
        self.assertFalse(s.pending);self.assertEqual(s.facts,{})
