"""Contract/commit evidence with synthetic model, not real semantic inference."""
import unittest,json
from copy import deepcopy
from backend.v2.companion import GUESS_CONSISTENCY,GUESS_REVIEW,ModelError
from backend.v2.diagnostics import contract_code
from tests.v2 import test_m05 as old

class Guess(unittest.IsolatedAsyncioTestCase):
    make=old.Integration.make
    turn=old.Integration.turn
    async def seed(self,answer='风筝'):
        self.make();self.model.next_plan.update(action='change',mode='guess',rules='瓦力出题孩子猜，不提前说答案',roles=['瓦力出题','孩子猜'],secrets={'answer':answer},sentences=['它要借助风。'])
        await self.turn('你出题我猜')
    async def test_current_answer_reaches_plan_and_correct_confirmation_can_be_acked(self):
        for answer in ('风筝','气球'):
            await self.seed(answer)
            self.model.next_plan.update(action='continue',sentences=[f'猜对了，就是{answer}。'])
            await self.turn(f'是不是{answer}？')
            instruction,data=[(i,d) for i,d in self.model.requests if '严格字段' in i][-1]
            self.assertEqual(data['context']['unrevealed'],{'answer':answer})
            self.assertIn(GUESS_CONSISTENCY,instruction)
            self.assertIn(f'猜对了，就是{answer}。',self.peer.session.public)
            safes=[(i,d) for i,d in self.model.requests if '审核下一个' in i]
            self.assertTrue(all(GUESS_REVIEW in i for i,d in safes))
    async def test_wrong_guess_preserves_hidden_and_consistent_clue_not_answer(self):
        await self.seed();self.model.next_plan.update(action='continue',secrets={},sentences=['还没猜中，它有一根长长的线。'])
        await self.turn('是不是气球？')
        self.assertEqual(self.peer.session.secrets,{'answer':'风筝'})
        self.assertNotIn('风筝',str(self.peer.session.context()['heard']))
        self.assertIn('它要借助风。',str(self.peer.session.context()['heard']))
        self.assertIn('一根长长的线',str(self.peer.session.context()['heard']))
    async def test_explicit_answer_substitution_rejected_without_overwrite_or_playback(self):
        await self.seed();before=deepcopy(self.peer.session.context());self.model.next_plan.update(action='continue',secrets={'answer':'雨伞'},sentences=['它不是原来的东西。'])
        context=self.peer.session.context()
        with self.assertRaises(ModelError) as caught:await self.providers.plan('再给线索',context)
        self.assertEqual(contract_code(caught.exception),'plan_guess_answer_changed')
        self.assertEqual(self.peer.session.context(),before)
    async def test_role_exchange_clears_old_answer_and_commits_new_role_only_after_ack(self):
        await self.seed();self.model.next_plan.update(action='change',secrets={},roles=['孩子出题','瓦力猜'],rules='孩子给线索瓦力猜',sentences=['这次我猜是太阳。'])
        await self.turn('换我出题你猜，白天照亮天空的是什么？')
        self.assertEqual(self.peer.session.secrets,{})
        self.assertEqual(self.peer.session.game['roles'],['孩子出题','瓦力猜'])
    async def test_review_rejection_prevents_inconsistent_candidate_commit(self):
        await self.seed();before=list(self.peer.session.public);self.model.allowed=False
        self.model.next_plan.update(action='continue',sentences=['不一致的合成候选。'])
        # Explicitly exercise rejection, not claim mock model detected semantics.
        p=self.peer;p.session.begin_turn();await p.commands()
        import asyncio
        p.generation=asyncio.create_task(p.respond('再提示一下',p.epoch))
        await p.handle(json.dumps(dict(v=2,type='bind',epoch=p.epoch,seq=p.sequence+1,player='p')))
        await p.generation
        self.assertEqual(p.session.public,before);self.assertFalse(p.session.pending)
        self.assertTrue(any(e['type']=='failure' for e in self.socket.events))
    async def test_contract_covers_nonliteral_guesses_and_no_automatic_substring_judge(self):
        self.assertIn('否定、引用、多个候选',GUESS_CONSISTENCY)
        self.assertIn('未猜中不得主动泄底',GUESS_REVIEW)
        self.assertIn('明确猜中后的如实确认允许',GUESS_REVIEW)
    async def test_actual_voicepeer_changed_secret_fails_before_any_new_audio_or_state(self):
        import asyncio
        await self.seed();p=self.peer;before=deepcopy(p.session.game);heard=list(p.session.public)
        frames=sum(e['type']=='audio' for e in self.socket.events)
        self.model.next_plan.update(action='continue',secrets={'answer':'雨伞'},sentences=['合成换谜底候选。'])
        p.session.begin_turn();await p.commands()
        p.generation=asyncio.create_task(p.respond('再给线索',p.epoch))
        await p.handle(json.dumps(dict(v=2,type='bind',epoch=p.epoch,seq=p.sequence+1,player='p')))
        await p.generation
        self.assertEqual(sum(e['type']=='audio' for e in self.socket.events),frames)
        self.assertEqual(p.session.game,before);self.assertEqual(p.session.public,heard)
        self.assertEqual(p.session.secrets,{'answer':'风筝'})
        self.assertEqual(p.last_failure['contract'],'plan_guess_answer_changed')

class GuessSwap(unittest.IsolatedAsyncioTestCase):
    make=old.Integration.make
    turn=old.Integration.turn
    async def test_swap_with_clue_replies_same_turn_and_never_stores_hypothesis(self):
        for clue,guess in [('长耳朵爱吃草','兔子'),('能在水里游有鳍','鱼')]:
            self.make();self.model.next_plan.update(action='change',mode='guess',guess_role='setter',secrets={'answer':'旧题'},sentences=['原题线索。'])
            await self.turn('你出题我猜')
            self.model.next_plan.update(action='change',guess_role='guesser',secrets={'answer':guess},sentences=[f'我猜是{guess}。'])
            await self.turn('换我出题你猜：'+clue)
            self.assertEqual(self.peer.session.game['guess_role'],'guesser')
            self.assertEqual(self.peer.session.secrets,{})
            self.assertIn(f'我猜是{guess}。',self.peer.session.public)
            instruction,data=[(i,d) for i,d in self.model.requests if '严格字段' in i][-1]
            self.assertEqual(data['text'],'换我出题你猜：'+clue)
            self.assertIn('同轮已经给了题目/线索',instruction)
    async def test_swap_without_clue_can_ask_for_question(self):
        self.make();self.model.next_plan.update(action='change',mode='guess',guess_role='guesser',secrets={},sentences=['好呀，请给我第一条线索。'])
        await self.turn('这次换我出题，你来猜')
        self.assertEqual(self.peer.session.secrets,{})
        self.assertIn('请给我第一条线索',str(self.peer.session.public))
    async def test_continued_guesser_does_not_restore_old_host_secret(self):
        self.make();self.peer.session.game={'mode':'guess','rules':'孩子出题瓦力猜','roles':[],'guess_role':'guesser'}
        self.peer.session.secrets={'answer':'过时主持答案'}
        self.model.next_plan.update(action='continue',mode='guess',secrets={'answer':'新推测'},sentences=['我猜是小狗。'])
        await self.turn('它汪汪叫，你猜呢')
        self.assertEqual(self.peer.session.game['guess_role'],'guesser')
        self.assertEqual(self.peer.session.secrets,{})
    async def test_raw_session_state_cannot_commit_guesser_with_host_secret(self):
        from backend.v2.session import Session
        s=Session(lambda:0);s.begin_turn();s.drain_commands();s.bind_player('p');s.drain_commands()
        state=dict(mode='guess',rules='',roles=[],secrets={'answer':'candidate'},guess_role='guesser')
        self.assertFalse(s.send(s.task('tts'),name='bad',public='合成候选',end=1,approved=True,state=state))
        self.assertFalse(s.pending);self.assertEqual(s.game,{})
    async def test_guesser_proposal_does_not_commit_without_ack(self):
        import asyncio
        self.make();self.socket.acknowledge=False
        self.model.next_plan.update(action='change',mode='guess',guess_role='guesser',secrets={},sentences=['我猜是小狗。'])
        p=self.peer;p.session.begin_turn();await p.commands();p.generation=asyncio.create_task(p.respond('换我问：汪汪叫的是什么',0))
        await p.handle(json.dumps(dict(v=2,type='bind',epoch=0,seq=0,player='p')))
        async with asyncio.timeout(1):
            while not p.session.pending:await asyncio.sleep(0)
        self.assertEqual(p.session.game,{})
        p.session.interrupt();await p.cancel_generation();self.assertEqual(p.session.game,{})
    async def test_role_type_invalid_is_fixed_diagnostic_not_unclassified_typeerror(self):
        for role in ([],{},True,1,'unknown'):
            self.make();self.model.next_plan.update(mode='guess',guess_role=role)
            with self.assertRaises(ModelError) as caught:await self.providers.plan('合成',{})
            self.assertEqual(contract_code(caught.exception),'plan_guess_role')
    async def test_compact_preserves_guess_role_and_legacy_non_guess_compatible(self):
        self.make();self.model.next_plan.update(action='change',mode='guess',guess_role='guesser',secrets={'answer':'模型错误封存'},sentences=['我猜是兔子。'])
        await self.turn('换我问你猜：长耳朵的是什么')
        s=self.peer.session
        self.assertEqual(self.peer.last_guess_normalization,'guesser_secrets_cleared')
        self.assertEqual(s.secrets,{})
        s.public.extend('合成背景'+str(i) for i in range(40))
        before=s.context()['game'];self.assertTrue(s.compact(s.memory_snapshot(),[]))
        self.assertEqual(s.context()['game'],before)
        self.model.next_plan.pop('guess_role');self.model.next_plan.update(action='leave',mode='chat',secrets={},sentences=['我们聊点别的。'])
        await self.turn('不猜了')
        self.assertNotIn('guess_role',s.game)
    async def test_private_role_proposal_cannot_change_public_game(self):
        self.make();self.model.next_plan.update(action='change',mode='guess',guess_role='setter',secrets={'answer':'原题'},sentences=['原题线索。'])
        await self.turn('你出题我猜');before=deepcopy(self.peer.session.game)
        self.model.next_plan.update(action='private',guess_role='guesser',secrets={},sentences=['私事合成回应。'])
        await self.turn('我想聊私事')
        self.assertEqual(self.peer.session.game,before)
        self.assertNotIn('私事合成回应',str(self.peer.session.context(shared=True)))
    async def test_held_current_capacity_reply_restores_original_guess_role(self):
        from unittest.mock import patch
        self.make();self.model.next_plan.update(action='change',mode='guess',guess_role='setter',secrets={'answer':'原题'},sentences=['原题线索。'])
        await self.turn('你出题我猜');before=deepcopy(self.peer.session.game)
        self.model.next_plan.update(action='change',guess_role='guesser',secrets={},sentences=['候选推测。'])
        with patch.object(self.peer.session,'record_input',return_value=False):await self.turn('合成新输入')
        self.assertEqual(self.peer.session.game,before)
        self.assertEqual(self.peer.session.secrets,{'answer':'原题'})
