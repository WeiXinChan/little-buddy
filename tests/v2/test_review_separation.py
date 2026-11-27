import asyncio,json,unittest
from copy import deepcopy
from types import SimpleNamespace
from backend.v2.review import ReviewDecision,QualityFault
from backend.v2.safety import SafetyFault
from backend.v2.voice import VoicePeer,Operation
from backend.v2.companion import UnifiedProviders,CompanionPolicy
from tests.v2 import test_m05 as old

class Model(old.Model):
    def __init__(self,verdicts):
        super().__init__(old.plan());self.verdicts=list(verdicts);self.reviews=[]
        self.next_plan.update(action='change',mode='association',rules='不重复',sentences=['合成已播开头。','合成后续候选。'])
    async def complete(self,instruction,data,*,schema=None):
        if '审核下一个' in instruction:
            self.reviews.append(deepcopy(data));return json.dumps(self.verdicts.pop(0))
        return await super().complete(instruction,data,schema=schema)

class Separation(unittest.IsolatedAsyncioTestCase):
    async def run_peer(self,verdicts):
        m=Model(verdicts);socket=old.Socket();p=VoicePeer(socket,UnifiedProviders(old.Speech(),m),CompanionPolicy());socket.peer=p
        p.session.begin_turn();await p.commands();p.generation=asyncio.create_task(p.respond('合成普通轮流游戏，不重复。',0))
        await p.handle(json.dumps(dict(v=2,type='bind',epoch=0,seq=0,player='p')));await p.generation
        return p,m,socket
    async def test_whole_quality_failure_stops_without_adult_help_or_state(self):
        p,m,s=await self.run_peer([{'allow':True,'quality':False}])
        self.assertFalse(p.session.public);self.assertEqual(p.session.game,{})
        failures=[e for e in s.events if e['type']=='failure'];self.assertEqual(failures[0]['code'],'voice')
        self.assertNotIn('local_help',str(failures));self.assertEqual(p.last_failure['kind'],'QualityFault')
        self.assertFalse(any(e['type']=='audio' for e in s.events))
    async def test_later_quality_failure_retains_only_actual_ack_no_final_state(self):
        p,m,s=await self.run_peer([{'allow':True,'quality':True},{'allow':True,'quality':True},{'allow':True,'quality':False}])
        self.assertEqual(p.session.public,['合成已播开头。']);self.assertEqual(p.session.game,{})
        self.assertNotIn('合成已播开头。',str(m.reviews[0]['context']['heard']))
        self.assertIn('合成已播开头。',str(m.reviews[-1]['context']['heard']))
        self.assertEqual(p.last_failure['stage'],'safety');self.assertEqual(p.last_failure['kind'],'QualityFault')
        self.assertFalse(any('local_help' in e for e in s.events));self.assertFalse(any(e['type']=='reply_end' for e in s.events))
    async def test_safety_has_priority_even_when_quality_also_false(self):
        p,m,s=await self.run_peer([{'allow':False,'quality':False}])
        self.assertTrue(any('local_help' in e and e['code']=='safety' for e in s.events))
        self.assertFalse(any(e['type']=='audio' for e in s.events));self.assertEqual(p.last_failure['kind'],'SafetyFault')
    async def test_missing_or_invalid_classification_is_review_unavailable(self):
        for value in ({'allow':True},{'allow':True,'quality':'true'},{'allow':False,'quality':True,'reason':'PRIVATE_CANARY'}):
            p,m,s=await self.run_peer([value]);self.assertEqual(p.last_failure['kind'],'SafetyFault')
            self.assertTrue(any(e.get('local_help',{}).get('reason')=='review_unavailable' for e in s.events))
            self.assertNotIn('PRIVATE_CANARY',str(s.events))
    async def test_all_review_gates_remain_before_each_segment(self):
        p,m,s=await self.run_peer([{'allow':True,'quality':True}]*3)
        self.assertEqual(len(m.reviews),3);self.assertEqual(p.session.public,['合成已播开头。','合成后续候选。'])
        self.assertEqual(p.session.game['rules'],'不重复')
    async def test_legacy_boolean_safety_provider_remains_supported_and_false_is_safety(self):
        for value in (True,False):
            async def safe(*args):return value
            p=VoicePeer(old.Socket(),SimpleNamespace(safe=safe),CompanionPolicy())
            if value:await p.review(Operation(p,0),'合成')
            else:
                with self.assertRaises(SafetyFault):await p.review(Operation(p,0),'合成')
    async def test_decision_rejects_nonboolean_fields(self):
        for value in ('false',[],{},0):
            with self.assertRaises(ValueError):ReviewDecision(True,value)
    async def test_direct_safe_boolean_compat_and_answer_raise_quality_not_safety(self):
        for value,wanted in [({'allow':True,'quality':True},True),({'allow':True,'quality':False},False),({'allow':False,'quality':True},False)]:
            provider=UnifiedProviders(old.Speech(),Model([value]))
            self.assertIs(await provider.safe('固定合成',{}),wanted)
        provider=UnifiedProviders(old.Speech(),Model([{'allow':True,'quality':False}]))
        with self.assertRaises(QualityFault):
            async with provider.answer('固定合成',{}) as sentences:
                async for _ in sentences:pass
    async def test_actual_http_adapter_uses_strict_dual_field_contract(self):
        import httpx
        from backend.v2.companion import DashScopeModel
        from backend.v2.models import TEXT_MODEL
        from backend.v2.release import selected
        seen=[]
        async def response(request):
            body=json.loads(request.content);seen.append(body)
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'{"allow":true,"quality":false}'}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
            speech=SimpleNamespace(llm=TEXT_MODEL,http=http,chat_url='https://synthetic.invalid/chat',headers={})
            decision=await UnifiedProviders(old.Speech(),DashScopeModel(speech)).review('合成普通重复词',{})
        self.assertTrue(decision.safety_allowed);self.assertFalse(decision.quality_allowed)
        self.assertEqual(seen[0]['model'],TEXT_MODEL);self.assertFalse(seen[0]['enable_thinking'])
        self.assertEqual(seen[0]['max_tokens'],1400)
        self.assertEqual(seen[0]['response_format']['type'],'json_object')
        contract=json.loads(seen[0]['messages'][0]['content'].split('输出契约JSON Schema：')[-1])
        self.assertEqual(set(contract['required']),{'allow','quality'})
        self.assertTrue(selected('backend/v2/review.py'))
