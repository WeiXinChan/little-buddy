"""Real Qwen HTTP adapter -> VoicePeer/ACK; pure quality gets at most one new riddle."""
import asyncio,json,unittest
from contextlib import asynccontextmanager
from copy import deepcopy
import httpx
from backend.dashscope import DashScope
from backend.v2.companion import DashScopeModel,UnifiedProviders,CompanionPolicy
from backend.v2.voice import VoicePeer
from tests.v2.test_m05 import Socket,Speech
from tests.v2.test_post_solo_probe import Clock

TEXT='我们来猜动物吧'
def candidate(answer='兔子',clue='它有长长的耳朵。'):
    return dict(action='change',mode='guess',guess_role='setter',rules='你猜我出题，每次一条线索',
        roles=['瓦力出题','孩子猜'],secrets={'answer':answer},sentences=[clue],anchors={'clue.current':0},tools=[])

class InitialGuess(unittest.IsolatedAsyncioTestCase):
    async def scenario(self,*,reviews=None,active=False,private=False,spent=False,replacement=None,
                       first=None,clock_expired=False,pause=False,quota_on_replacement=False):
        calls=[];tts=[];review_count=0;plan_count=0;facts_count=0
        ready=asyncio.Event();release=asyncio.Event();clock=Clock()
        original=deepcopy(first or candidate());replacement=deepcopy(replacement or candidate('猫','它会喵喵叫。'))
        reviews=list(reviews or [{'allow':True,'quality':False},{'allow':True,'quality':True}])
        async def response(request):
            nonlocal review_count,plan_count,facts_count
            body=json.loads(request.content);calls.append(body);instruction=body['messages'][0]['content']
            if '提取孩子' in instruction:facts_count+=1;value={'facts':[]}
            elif '审核下一个' in instruction:
                value=reviews[min(review_count,len(reviews)-1)];review_count+=1
                if value=='error':return httpx.Response(503)
            else:
                plan_count+=1;value=original if plan_count==1 else replacement
                if plan_count==2 and quota_on_replacement:return httpx.Response(403,json={'error':{'code':'AllocationQuota.FreeTierOnly'}})
                if plan_count==2 and pause:ready.set();await release.wait()
                if plan_count==2 and clock_expired:clock.now=115
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value,ensure_ascii=False)}}]})
        http=httpx.AsyncClient(transport=httpx.MockTransport(response));self.addAsyncCleanup(http.aclose)
        model=DashScopeModel(DashScope(http,workspace='synthetic',region='cn-beijing',key='SYNTHETIC',
            asr='fake',llm='qwen3.8-omni-flash',tts='fake',voice='fake'))
        class CountSpeech(Speech):
            @asynccontextmanager
            async def synthesize(self,text,rate):
                tts.append(text)
                async with super().synthesize(text,rate) as chunks:yield chunks
        wire=Socket();peer=VoicePeer(wire,UnifiedProviders(CountSpeech(),model),CompanionPolicy(),clock=clock);wire.peer=peer
        if active:peer.session.game={'mode':'guess','guess_role':'setter'};peer.session.secrets={'answer':'兔子'}
        peer.session.private_mode=private
        peer.input_budget.speech(0);peer.session.begin_turn();peer.session.drain_commands()
        if spent:peer.input_budget.read_retry_revision=peer.revision
        peer.session.heartbeat_deadline=1000
        peer.generation=asyncio.create_task(peer.respond(TEXT,0))
        await peer.handle(json.dumps(dict(v=2,type='bind',epoch=0,seq=0,player='synthetic')))
        if pause:
            await asyncio.wait_for(ready.wait(),1)
            await peer.handle(json.dumps(dict(v=2,type='advance',epoch=0,seq=1,revision=1)))
            release.set()
        await asyncio.wait_for(peer.generation,2)
        self.assertTrue(all(c['model']=='qwen3.8-omni-flash' for c in calls))
        return peer,calls,tts,(plan_count,facts_count,review_count)

    async def test_pure_quality_once_new_plan_full_review_then_only_approved_clue_commits(self):
        peer,calls,tts,counts=await self.scenario()
        self.assertEqual(counts,(2,1,2));self.assertEqual(len(calls),5)
        self.assertEqual(peer.last_guess_quality_repair,dict(initial_whole_quality_rejected=True,attempted=True,replacement_whole_approved=True))
        self.assertEqual(tts,['它会喵喵叫。']);self.assertEqual(peer.session.secrets,{'answer':'猫'})
        self.assertNotIn('它有长长的耳朵。',str(peer.session.public))
        self.assertEqual(sum(r['role']=='child' for r in peer.session.recent),1)
        self.assertEqual(peer.input_budget.deadline,115);self.assertEqual(peer.input_budget.read_retry_revision,0)
        plans=[c for c in calls if '严格字段' in c['messages'][0]['content']]
        self.assertEqual(json.loads(plans[1]['messages'][1]['content'])['server_constraints']['correction'],'initial_guess_quality')
        self.assertNotIn('initial_guess_quality表示',plans[0]['messages'][0]['content'])
        self.assertIn('initial_guess_quality表示',plans[1]['messages'][0]['content'])

    async def test_first_pass_does_not_add_any_request(self):
        _,calls,tts,counts=await self.scenario(reviews=[{'allow':True,'quality':True}])
        self.assertEqual(counts,(1,1,1));self.assertEqual(len(calls),3);self.assertEqual(len(tts),1)

    async def test_safety_denial_malformed_or_review_exception_never_enters_quality_retry(self):
        for verdict in ({'allow':False,'quality':False},{'allow':True,'quality':'false'},'error'):
            with self.subTest(verdict=verdict):
                peer,calls,tts,counts=await self.scenario(reviews=[verdict])
                self.assertEqual(counts,(1,1,1));self.assertFalse(tts)
                self.assertEqual(peer.last_failure['kind'],'SafetyFault')

    async def test_second_quality_or_safety_denial_stops_without_third_plan_or_audio(self):
        for second in ({'allow':True,'quality':False},{'allow':False,'quality':False},'error'):
            peer,calls,tts,counts=await self.scenario(reviews=[{'allow':True,'quality':False},second])
            self.assertEqual(counts,(2,1,2));self.assertFalse(tts)
            self.assertEqual(peer.last_failure['kind'],'QualityFault' if isinstance(second,dict) and second['allow'] else 'SafetyFault')
            self.assertFalse(peer.session.game)

    async def test_continuation_private_or_shared_retry_used_do_not_get_new_riddle(self):
        for option in ('active','private','spent'):
            first=candidate()
            if option=='private':first['action']='continue'
            peer,calls,tts,counts=await self.scenario(first=first,**{option:True})
            self.assertEqual(counts,(1,1,1));self.assertFalse(tts)
            self.assertEqual(peer.last_failure['kind'],'QualityFault')
            self.assertEqual(peer.last_failure['detail'],'quality_whole')

    async def test_new_proposal_still_strictly_validated(self):
        for bad in ({**candidate(),'mode':'invented'},{**candidate(),'guess_role':'guesser'},
                    {**candidate(),'action':'private'}):
            peer,calls,tts,counts=await self.scenario(replacement=bad)
            self.assertEqual(counts,(2,1,1));self.assertFalse(tts)
            self.assertIn(peer.last_failure['kind'],('ModelError','WireError'))

    async def test_segment_quality_denial_does_not_regenerate(self):
        first=candidate();first['sentences']=['第一条线索。','第二条线索。']
        peer,calls,tts,counts=await self.scenario(first=first,reviews=[{'allow':True,'quality':True},{'allow':True,'quality':False}])
        self.assertEqual(counts,(1,1,2));self.assertFalse(tts)
        self.assertEqual(peer.last_failure['detail'],'quality_segment')

    async def test_quality_after_first_played_segment_never_changes_riddle(self):
        first=candidate();first['sentences']=['第一条线索。','第二条线索。']
        peer,calls,tts,counts=await self.scenario(first=first,reviews=[{'allow':True,'quality':True},
            {'allow':True,'quality':True},{'allow':True,'quality':False}])
        self.assertEqual(counts,(1,1,3));self.assertEqual(tts,['第一条线索。'])
        self.assertFalse(peer.session.game);self.assertFalse(peer.session.secrets)

    async def test_guesser_never_gets_setter_regeneration(self):
        first=candidate();first['guess_role']='guesser';first['secrets']={}
        _,_,tts,counts=await self.scenario(first=first)
        self.assertEqual(counts,(1,1,1));self.assertFalse(tts)

    async def test_quota_on_replacement_stops_without_fallback(self):
        peer,calls,tts,counts=await self.scenario(quota_on_replacement=True)
        self.assertEqual(counts,(2,1,1));self.assertFalse(tts)
        self.assertEqual([e['code'] for e in peer.socket.events if e['type']=='failure'],['quota'])

    async def test_deadline_is_not_renewed_by_regeneration(self):
        peer,calls,tts,counts=await self.scenario(clock_expired=True)
        self.assertEqual(counts,(2,1,1));self.assertFalse(tts);self.assertEqual(peer.input_budget.deadline,115)

    async def test_advance_during_regeneration_drops_late_candidate_without_second_review(self):
        peer,calls,tts,counts=await self.scenario(pause=True)
        self.assertEqual(counts,(2,1,1));self.assertFalse(tts);self.assertEqual(peer.revision,1)
        self.assertFalse([e for e in peer.socket.events if e['type']=='failure'])

class RepairMetadata(unittest.TestCase):
    def test_fixed_scalars_only_no_draft_or_error_prose(self):
        from scripts.v2_multiturn_probe import guess_quality_repair
        class Peer:last_guess_quality_repair={'initial_whole_quality_rejected':True,'attempted':True,'replacement_whole_approved':False}
        peer=Peer();self.assertEqual(guess_quality_repair(peer),peer.last_guess_quality_repair)
        peer.last_guess_quality_repair=dict(peer.last_guess_quality_repair,draft='PRIVATE')
        self.assertIsNone(guess_quality_repair(peer))
