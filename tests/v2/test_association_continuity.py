"""Synthetic semantic-contract/ACK-path controls, not a real-model oracle."""
import asyncio,json,unittest
from copy import deepcopy
from backend.v2.companion import ASSOCIATION_CONTINUITY
from tests.v2 import test_m05 as old

class Continuity(unittest.IsolatedAsyncioTestCase):
    make=old.Integration.make
    turn=old.Integration.turn
    async def seed(self):
        self.make();self.model.next_plan.update(action='change',mode='association',rules='轮流说水果，不重复',sentences=['我说香蕉。'])
        await self.turn('轮流说水果，不重复，我先火龙果。')
        self.model.next_plan.update(action='continue',sentences=['我说荔枝。'])
        await self.turn('我说草莓，轮到你，不要重复。')
    async def test_explicit_partial_change_keeps_old_words_rules_and_current_input(self):
        await self.seed();sid=self.peer.session.session
        self.model.next_plan.update(action='change',rules='只说两个字的水果，轮流，不重复',sentences=['好，我说柚子。'])
        await self.turn('只改成两个字的水果，不重新开始，仍然不重复。我说菠萝。')
        instruction,data=[(i,d) for i,d in self.model.requests if '严格字段' in i][-1]
        self.assertEqual(self.peer.session.session,sid)
        self.assertIn('香蕉',str(data['context']['heard']));self.assertIn('荔枝',str(data['context']['heard']))
        self.assertIn('草莓',str(data['context']['recent']));self.assertIn('不重复',data['context']['game']['rules'])
        self.assertIn(ASSOCIATION_CONTINUITY,instruction)
        self.assertEqual(self.peer.session.public.count('我说香蕉。'),1)
        self.assertEqual(self.peer.session.public[-1],'好，我说柚子。')
    async def test_explicit_restart_can_reuse_old_word_without_erasing_history(self):
        await self.seed();prior=list(self.peer.session.public)
        self.model.next_plan.update(action='change',rules='新一轮水果接龙，不重复，从这次开始计词',sentences=['新一轮我说香蕉。'])
        await self.turn('重新开始新一轮，旧词可以再用，我先苹果。')
        self.assertEqual(self.peer.session.public[:len(prior)],prior)
        self.assertEqual(self.peer.session.public[-1],'新一轮我说香蕉。')
        self.assertIn('新一轮',self.peer.session.game['rules'])
    async def test_ambiguous_my_first_may_clarify_without_silent_reset(self):
        await self.seed();rules=self.peer.session.game['rules'];prior=list(self.peer.session.public)
        self.model.next_plan.update(action='continue',sentences=['你想重新开一轮，还是接着刚才的玩？'])
        await self.turn('改成两个字，我先香蕉。')
        self.assertEqual(self.peer.session.game['rules'],rules)
        self.assertEqual(self.peer.session.public[:len(prior)],prior)
        self.assertIn('重新开一轮',self.peer.session.public[-1])
    async def test_review_can_block_duplicate_before_any_new_audio_or_state(self):
        await self.seed();prior=list(self.peer.session.public);state=deepcopy(self.peer.session.game)
        frames=sum(e['type']=='audio' for e in self.socket.events)
        self.model.allowed=False;self.model.next_plan.update(action='change',rules='两个字水果，不重复',sentences=['我说香蕉。'])
        p=self.peer;p.session.begin_turn();await p.commands();p.generation=asyncio.create_task(p.respond('只改字数，不重开',p.epoch))
        await p.handle(json.dumps(dict(v=2,type='bind',epoch=p.epoch,seq=p.sequence+1,player='p')));await p.generation
        self.assertEqual(p.session.public,prior);self.assertEqual(p.session.game,state)
        self.assertEqual(sum(e['type']=='audio' for e in self.socket.events),frames)
        safes=[i for i,d in self.model.requests if '审核下一个' in i]
        self.assertTrue(safes and all(ASSOCIATION_CONTINUITY in i for i in safes))
    async def test_no_ack_rule_change_remains_uncommitted(self):
        await self.seed();prior=deepcopy(self.peer.session.game);self.socket.acknowledge=False
        self.model.next_plan.update(action='change',rules='两个字水果，不重复',sentences=['我说柚子。'])
        p=self.peer;p.session.begin_turn();await p.commands();p.generation=asyncio.create_task(p.respond('只改字数，不重开',p.epoch))
        await p.handle(json.dumps(dict(v=2,type='bind',epoch=p.epoch,seq=p.sequence+1,player='p')))
        async with asyncio.timeout(1):
            while not p.session.pending:await asyncio.sleep(0)
        self.assertEqual(p.session.game,prior);p.session.interrupt();await p.cancel_generation()
        self.assertEqual(p.session.game,prior)
