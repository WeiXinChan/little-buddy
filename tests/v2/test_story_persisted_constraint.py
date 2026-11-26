"""Server-owned rule receipts commit only with the original final ACK."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import unittest
from backend.v2.story_rules import obeys_turn_limit
from backend.v2.companion import UnifiedProviders,CompanionPolicy,ModelError
from backend.v2.voice import VoicePeer
from tests.v2 import test_m05 as fixtures

class Persisted(unittest.IsolatedAsyncioTestCase):
    async def test_root_original_persisted_paraphrase_counterexample(self):
        x=json.loads(Path('docs/testing/v2/story-turn-rule/persisted/root-counterexample.json').read_text())
        self.assertEqual(obeys_turn_limit(x['input'],x['context'],x['plan']),x['expected_accepted'])

    def make(self):
        self.model=fixtures.Model(fixtures.plan());self.model.next_plan.update(mode='story',rules='轮流编故事，一人接一句',anchors={})
        self.socket=fixtures.Socket();self.peer=VoicePeer(self.socket,UnifiedProviders(fixtures.Speech(),self.model),CompanionPolicy());self.socket.peer=self.peer
        async def close():
            await self.peer.cancel_generation();self.peer.session.clear()
        self.addAsyncCleanup(close)

    async def turn(self,text):
        p=self.peer;p.session.begin_turn();p.session.drain_commands();self.socket.events.clear()
        p.generation=asyncio.create_task(p.respond(text,p.epoch))
        await p.handle(json.dumps(dict(v=2,type='bind',epoch=p.epoch,seq=p.sequence+1,player='test')))
        await p.generation

    async def test_actual_committed_constraint_survives_arbitrary_model_rule_rewrite_and_change_action(self):
        self.make();await self.turn('我们一人一句编故事。')
        self.assertEqual(self.peer.session.game['turn_limit'],1)
        old=deepcopy(self.peer.session.game);heard=tuple(self.peer.session.public)
        self.model.next_plan.update(rules='接续这个精彩故事',action='change',sentences=['小猫看见星星。','飞船继续前进。'])
        await self.turn('然后它遇到一颗蓝色星星。')
        self.assertFalse(any(e['type']=='audio' for e in self.socket.events))
        self.assertEqual(self.peer.session.game,old);self.assertEqual(tuple(self.peer.session.public),heard)

    async def test_legacy_model_promise_bootstraps_once_and_no_model_receipt_is_trusted(self):
        self.make();self.peer.session.game={'mode':'story','rules':'轮流编故事，一人接一句','roles':[]}
        await self.turn('接着讲。')
        self.assertEqual(self.peer.session.game['turn_limit'],1)
        self.model.next_plan['turn_limit']=4
        with self.assertRaises(ModelError):await self.peer.providers.plan('继续。',self.peer.session.context())
        self.model.next_plan.pop('turn_limit');self.model.next_plan['_story_turn_limit']=4
        with self.assertRaises(ModelError):await self.peer.providers.plan('继续。',self.peer.session.context())

    async def test_explicit_two_sentence_change_cancel_and_leave_commit_legally(self):
        self.make();await self.turn('每人说一句。')
        self.model.next_plan.update(action='change',rules='换一种节奏',sentences=['小猫出发。','星星亮了。'])
        await self.turn('不要再一人一句了，改成每人两句。')
        self.assertEqual(self.peer.session.game['turn_limit'],2)
        self.model.next_plan.update(action='continue',rules='又被模型改写',sentences=['小猫出发。','星星亮了。'])
        await self.turn('继续。');self.assertEqual(self.peer.session.game['turn_limit'],2)
        self.model.next_plan['sentences']=['小猫出发。','星星亮了。','飞船停下。']
        await self.turn('不要再每人两句了。')
        self.assertIsNone(self.peer.session.game['turn_limit'])
        await self.turn('继续。');self.assertIsNone(self.peer.session.game['turn_limit'])
        self.model.next_plan['sentences']=['小猫出发。']
        await self.turn('重新每人一句。');self.assertEqual(self.peer.session.game['turn_limit'],1)
        self.model.next_plan['sentences']=['小猫出发。','星星亮了。']
        await self.turn('取消句数限制。');self.assertIsNone(self.peer.session.game['turn_limit'])
        self.model.next_plan.update(action='leave',mode='chat',rules='',sentences=['聊聊云吧。'])
        await self.turn('不玩故事了。');self.assertNotIn('turn_limit',self.peer.session.game)

    async def test_partial_final_ack_does_not_commit_constraint_then_final_ack_does(self):
        from dataclasses import asdict,replace
        self.make();self.socket.acknowledge=False
        p=self.peer;p.session.begin_turn();p.session.drain_commands()
        generation=asyncio.create_task(p.respond('我们每人说一句。',p.epoch));p.generation=generation
        await p.handle(json.dumps(dict(v=2,type='bind',epoch=p.epoch,seq=0,player='test')))
        for _ in range(100):
            if any(item.state is not None for item in p.session.pending):break
            await asyncio.sleep(.001)
        self.assertTrue(p.session.pending);self.assertNotIn('turn_limit',p.session.game)
        sequence=0
        async def ack(item,head):
            nonlocal sequence
            identity=asdict(replace(p.ack_identity,sequence=sequence));sequence+=1
            await p.handle(json.dumps(dict(v=2,type='ack',epoch=p.epoch,seq=p.sequence+1,identity=identity,player='test',stream=p.session.stream,segment=item.name,head=head)))
        for _ in range(12):
            if not p.session.pending:break
            await asyncio.sleep(0)
            item=p.session.pending[0]
            if item.state is not None:
                await ack(item,item.end-1);self.assertNotIn('turn_limit',p.session.game)
            await ack(item,item.end)
        self.assertFalse(p.session.pending)
        await generation;self.assertEqual(p.session.game['turn_limit'],1)

    async def test_no_ack_cancellation_keeps_old_constraint_not_new_proposal(self):
        self.make();await self.turn('我们每人说一句。')
        self.model.next_plan.update(action='change',sentences=['小猫出发。','星星亮了。'])
        self.socket.acknowledge=False;p=self.peer;p.session.begin_turn();p.session.drain_commands()
        p.generation=asyncio.create_task(p.respond('改成每人两句。',p.epoch))
        await p.handle(json.dumps(dict(v=2,type='bind',epoch=p.epoch,seq=p.sequence+1,player='test')))
        for _ in range(100):
            if p.session.pending:break
            await asyncio.sleep(.001)
        self.assertTrue(p.session.pending);self.assertEqual(p.session.game['turn_limit'],1)
        await p.handle(json.dumps(dict(v=2,type='stop',epoch=p.epoch+1,seq=0,intent='cancel-test')))
        self.assertEqual(p.session.game['turn_limit'],1);self.assertFalse(p.session.pending)

    async def test_private_output_and_capacity_fallback_do_not_replace_public_constraint(self):
        from unittest.mock import patch
        self.make();await self.turn('我们每人一句。')
        with patch.object(self.peer.session,'record_input',return_value=False):
            await self.turn('改成每人两句。')
        self.assertEqual(self.peer.session.game['turn_limit'],1)
        self.model.next_plan.update(action='private',sentences=['我听你说。'])
        await self.turn('我想说私事，改成每人两句。')
        self.assertEqual(self.peer.session.game['turn_limit'],1)
        self.peer.session.handoff();self.assertEqual(self.peer.session.game,{})

    async def test_core_rejects_invalid_structured_constraint_and_detaches_valid_proposal(self):
        self.make();await self.turn('我们每人一句。')
        self.assertEqual(self.peer.session.game['turn_limit'],1)
        # The field is carried by normal state, hence original Session deepcopy,
        # size checks, private gate and ACK atomicity apply, no parallel store.
        state={'mode':'story','rules':'x','roles':[],'secrets':{},'turn_limit':1}
        from backend.v2.session import Session
        s=Session(lambda:0);s.begin_turn();s.bind_player('p');identity=s.task('tts')
        for value in (True,0,5,'1',[]):
            state['turn_limit']=value
            self.assertFalse(s.send(identity,name='x',public='x',end=1,approved=True,state=state))
        state['turn_limit']=1
        self.assertTrue(s.send(identity,name='x',public='x',end=1,approved=True,state=state))
        state['turn_limit']=4;self.assertEqual(s.pending[0].state['turn_limit'],1)
