"""Three real VoicePeer turns with production HTTP adapter, controlled semantics."""
import asyncio,json,unittest
from copy import deepcopy
import httpx
from backend.dashscope import DashScope
from backend.v2.companion import DashScopeModel,UnifiedProviders,CompanionPolicy
from backend.v2.voice import VoicePeer
from tests.v2.test_m05 import Socket,Speech
from tests.v2.test_initial_guess_quality import candidate

NEW='再给我出一个新的动物谜语吧。'
class NewGuessRound(unittest.IsolatedAsyncioTestCase):
    async def scenario(self,*,query=NEW,action='change',clue='它会喵喵叫。',ack=True,omit_role=False,deny_first=False,with_budget=False,both_flags=False):
        answer='大象' if omit_role else '猫'
        reviews=[];plans=[];tts=[];calls=[]
        class CountSpeech(Speech):
            def synthesize(self,text,rate):tts.append(text);return super().synthesize(text,rate)
        async def response(request):
            body=json.loads(request.content);i=body['messages'][0]['content'];d=json.loads(body['messages'][1]['content'])
            calls.append((i,deepcopy(d)))
            if '提取孩子' in i:value={'facts':[]}
            elif '审核下一个' in i:
                reviews.append((deepcopy(d),deepcopy(peer.session.game),deepcopy(peer.session.secrets),list(peer.session.public)))
                pending=d.get('pending_guess',{})
                if len(plans)==1:value={'allow':True,'quality':True}
                elif len(plans)==2:value={'allow':True,'quality':True}
                else:
                    value={'allow':answer not in d['segment'],
                           'quality':d.get('pending_guess_kind')=='replacement' and d.get('current_input')==NEW and
                           pending.get('answer')==answer and d['segment'] in ((clue,) if omit_role else ('它会喵喵叫。','它有软软的爪子。','它会喵喵叫。它有软软的爪子。'))}
                if deny_first and len(plans)==3:value={'allow':True,'quality':False}
            else:
                plans.append(deepcopy(d))
                value=candidate()
                if len(plans)==2:value.update(action='continue',sentences=['对啦！就是兔子。'],anchors={})
                if len(plans)>=3:
                    value=candidate(answer,clue);value['action']=action
                    if omit_role:value.pop('guess_role')
                    if isinstance(clue,list):value['sentences']=clue
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value,ensure_ascii=False)}}]})
        http=httpx.AsyncClient(transport=httpx.MockTransport(response));self.addAsyncCleanup(http.aclose)
        model=DashScopeModel(DashScope(http,workspace='synthetic',region='cn-beijing',key='SYNTHETIC',asr='fake',llm='qwen3.8-omni-flash',tts='fake',voice='fake'))
        wire=Socket();peer=VoicePeer(wire,UnifiedProviders(CountSpeech(),model),CompanionPolicy(),clock=lambda:100,
            animal_cards_enabled=both_flags,wide_audio_window=both_flags);wire.peer=peer
        async def turn(text):
            peer.session.begin_turn();peer.session.drain_commands()
            peer.generation=asyncio.create_task(peer.respond(text,peer.epoch))
            await peer.handle(json.dumps(dict(v=2,type='bind',epoch=peer.epoch,seq=peer.sequence+1,player='synthetic')))
            return peer.generation
        await asyncio.wait_for(await turn('请根据动物的耳朵给我出一道谜语。' if both_flags else '我们来猜动物吧'),2)
        await asyncio.wait_for(await turn('是兔子！'),2)
        before=(deepcopy(peer.session.game),deepcopy(peer.session.secrets),list(peer.session.public))
        reviews.clear();tts.clear();calls.clear();wire.acknowledge=ack
        if deny_first or with_budget:peer.input_budget.speech(0)
        task=await turn(query)
        if not ack:
            async with asyncio.timeout(1):
                while not peer.session.pending and not task.done():await asyncio.sleep(0)
            peer.session.interrupt();await peer.cancel_generation()
        else:await asyncio.wait_for(task,2)
        return peer,wire,reviews,plans,tts,calls,before

    async def test_explicit_new_riddle_uses_independent_proposal_and_commits_only_after_ack(self):
        p,w,reviews,plans,tts,calls,before=await self.scenario()
        self.assertEqual(len(plans),3);self.assertEqual(len(calls),3)
        self.assertEqual(tts,['它会喵喵叫。']);self.assertIsNone(getattr(p,'last_failure',None))
        d,game,secrets,heard=reviews[0]
        self.assertEqual(d['pending_guess_kind'],'replacement');self.assertEqual(d['current_input'],NEW)
        self.assertEqual(d['context']['unrevealed'],{'answer':'兔子'})
        self.assertEqual(d['pending_guess']['answer'],'猫');self.assertEqual((game,secrets,heard),before)
        self.assertEqual(p.session.secrets,{'answer':'猫'});self.assertEqual(p.session.public[-1],'它会喵喵叫。')
        self.assertNotIn('pending_guess',p.session.context());self.assertFalse(p.session.pending)
        instruction=next(i for i,d in calls if '严格字段' in i)
        self.assertIn('此时必须action=change',instruction)
        self.assertIn('不能用action=continue同时改变secrets',instruction)

    async def test_omitted_role_new_round_first_and_repaired_review_use_new_answer(self):
        p,_,reviews,plans,tts,calls,before=await self.scenario(omit_role=True,deny_first=True,clue='它有长长的象鼻。')
        self.assertEqual(len(plans),4);self.assertEqual(len(reviews),2)
        for d,game,secrets,heard in reviews:
            self.assertEqual(d['pending_guess_kind'],'replacement');self.assertEqual(d['pending_guess']['guess_role'],'setter')
            self.assertEqual(d['pending_guess']['answer'],'大象');self.assertEqual((game,secrets,heard),before)
        self.assertEqual(tts,['它有长长的象鼻。']);self.assertEqual(p.session.secrets,{'answer':'大象'})
        self.assertEqual(plans[-1]['server_constraints']['correction'],'new_guess_quality')

    async def test_new_round_budget_never_retries_safety_or_unrequested_change(self):
        for query,line,count in [(NEW,'答案是猫。',1),('不要换题','它会喵喵叫。',1),
                                 (NEW,'它有长长的象鼻。',2)]:
            p,_,reviews,plans,tts,_,before=await self.scenario(query=query,clue=line,with_budget=True)
            self.assertEqual(len(reviews),count);self.assertEqual(len(plans),2+count)
            self.assertFalse(tts);self.assertEqual((p.session.game,p.session.secrets,p.session.public),before)

    async def test_free_riddle_with_cards_and_wide_window_enabled(self):
        p,_,reviews,plans,tts,calls,before=await self.scenario(omit_role=True,deny_first=True,
            clue='它有长长的象鼻。',both_flags=True)
        self.assertIsNone(p.card_owner);self.assertEqual(p.session.audio_capacity,4)
        self.assertEqual(len(plans),4);self.assertEqual(len(reviews),2)
        for data,game,secrets,heard in reviews:
            self.assertEqual((game,secrets,heard),before)
            self.assertEqual(data['context']['unrevealed'],{'answer':'兔子'})
            self.assertEqual(data['pending_guess']['answer'],'大象')
            self.assertEqual(data['pending_guess_kind'],'replacement')
        instructions=[i for i,d in calls if d.get('pending_guess_kind')=='replacement']
        self.assertEqual(len(instructions),2)
        for instruction in instructions:
            self.assertIn('pending_guess.answer才是本轮新线索的核验对象',instruction)
            self.assertNotIn('审核猜谜片段须对照当前context.unrevealed',instruction)
        self.assertEqual(tts,['它有长长的象鼻。']);self.assertEqual(p.session.secrets,{'answer':'大象'})

    async def test_continue_changed_answer_stays_rejected_before_review_audio_or_commit(self):
        p,w,reviews,plans,tts,calls,before=await self.scenario(action='continue')
        self.assertEqual(p.last_failure['contract'],'plan_guess_answer_changed')
        self.assertEqual(len(plans),3);self.assertFalse(reviews);self.assertFalse(tts)
        self.assertEqual((p.session.game,p.session.secrets,p.session.public),before)

    async def test_unrequested_replacement_does_not_borrow_change_authority(self):
        for query in ('再提示一下原来那题','不要换题','他说再来一题，但我还想猜原题','是兔子！'):
            with self.subTest(query=query):
                p,w,reviews,plans,tts,calls,before=await self.scenario(query=query)
                self.assertEqual(p.last_failure['kind'],'QualityFault');self.assertFalse(tts)
                self.assertEqual((p.session.game,p.session.secrets,p.session.public),before)
                self.assertEqual(len(calls),3);self.assertFalse(p.session.pending)

    async def test_wrong_new_clue_quality_and_answer_leak_safety_still_fail_closed(self):
        for clue,kind in [('它有长长的象鼻。','QualityFault'),('答案是猫。','SafetyFault')]:
            with self.subTest(clue=clue):
                p,w,reviews,plans,tts,calls,before=await self.scenario(clue=clue)
                self.assertEqual(p.last_failure['kind'],kind);self.assertFalse(tts)
                self.assertEqual((p.session.game,p.session.secrets,p.session.public),before)
                self.assertEqual(len(calls),3)

    async def test_new_riddle_without_ack_keeps_old_answer_and_played_history(self):
        p,w,reviews,plans,tts,calls,before=await self.scenario(ack=False)
        self.assertEqual((p.session.game,p.session.secrets,p.session.public),before)
        self.assertFalse(p.session.pending);self.assertFalse(p.quarantined)
        self.assertFalse(any(not t.done() for t in p.retired_tasks))

    async def test_each_new_round_segment_keeps_candidate_separate_until_final_ack(self):
        p,w,reviews,plans,tts,calls,before=await self.scenario(clue=['它会喵喵叫。','它有软软的爪子。'])
        self.assertEqual([d['review_phase'] for d,g,s,h in reviews],['whole','segment','segment'])
        for d,g,s,h in reviews:
            self.assertEqual(d['current_input'],NEW);self.assertEqual(d['pending_guess_kind'],'replacement')
            self.assertEqual(d['pending_guess']['answer'],'猫');self.assertEqual(s,{'answer':'兔子'})
        self.assertEqual(reviews[-1][3][-1],'它会喵喵叫。')
        self.assertEqual(p.session.secrets,{'answer':'猫'});self.assertEqual(len(calls),5)
        self.assertIsNone(getattr(p,'last_failure',None));self.assertFalse(p.session.pending)
