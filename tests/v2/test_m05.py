"""Production adapter integration with explicitly synthetic structured model responses."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import json
import unittest
import httpx
from backend.v2.companion import UnifiedProviders, DashScopeModel, CompanionPolicy, ModelError
from backend.v2.voice import VoicePeer, VoiceFault
from backend.v2.session import Session
from backend.dashscope import DashScope

def plan(**kw):
    return dict(action='continue', mode='chat', rules='', roles=[], secrets={},
                sentences=['我们一起玩吧。'], **kw)

class Speech:
    @asynccontextmanager
    async def synthesize(self, text, rate):
        async def frames():
            yield b'\x01\x00' * 6000  # Real adapter must reframe oversized supplier PCM.
        yield frames()

class Model:
    def __init__(self, next_plan):
        self.next_plan = next_plan
        self.requests = []
        self.keep = list(range(24))
        self.extracted = []
        self.allowed = True
    async def complete(self, instruction, data, *, schema=None):
        self.requests.append((instruction, data))
        if '审核下一个' in instruction: result = dict(allow=self.allowed,quality=True)
        elif '提取孩子' in instruction: result = dict(facts=[{k:f[k] for k in ('key','value')} for f in self.extracted])
        elif '只返回JSON {"keep"' in instruction: result = dict(keep=self.keep)
        elif 'completion:' in instruction:
            result = dict(completion='complete', meaning='new_turn')
        else: result = self.next_plan
        return json.dumps(result, ensure_ascii=False)

class Socket:
    def __init__(self):
        self.peer = None; self.events=[]; self.acknowledge=True
    async def send(self, raw):
        e=json.loads(raw); self.events.append(e)
        if e['type']=='audio' and self.acknowledge:
            p=self.peer
            i=replace(p.ack_identity, sequence=p.ack_sequence)
            p.ack_sequence+=1
            p.session.ack(i, player=e['player'], stream=e['stream'], segment=e['segment'], head=e['end'])
            p.changed.set()
    async def close(self,*args): pass

class Integration(unittest.IsolatedAsyncioTestCase):
    def make(self, next_plan=None):
        self.model=Model(next_plan or plan())
        self.providers=UnifiedProviders(Speech(),self.model)
        self.socket=Socket()
        self.peer=VoicePeer(self.socket,self.providers,CompanionPolicy())
        self.socket.peer=self.peer
    async def turn(self,text):
        p=self.peer
        p.session.begin_turn(); p.session.drain_commands()
        p.generation=asyncio.create_task(p.respond(text,p.epoch))
        await p.handle(json.dumps(dict(v=2,type='bind',epoch=p.epoch,seq=p.sequence+1,player='p')))
        await asyncio.wait_for(p.generation,2)
        if p.prepared is not None:
            decision = p.prepared
            await p.handle(json.dumps(dict(v=2,type='stop',epoch=p.epoch+1,seq=0,intent=decision[2])))
            await p.handle(json.dumps(dict(v=2,type='bind',epoch=p.epoch,seq=1,player='fresh')))
            await asyncio.wait_for(p.generation,2)
        self.assertFalse(any(e['type']=='failure' for e in self.socket.events),self.socket.events)
    async def test_child_preference_cross_turn_and_played_dialogue_relation(self):
        self.make()
        self.model.extracted=[dict(key='preference',start=0,end=4,value='我喜欢猫')]
        await self.turn('我喜欢猫')
        self.model.extracted=[]
        await self.turn('刚才我说喜欢什么？')
        received=[d for i,d in self.model.requests if '严格字段' in i][-1]['context']
        self.assertEqual(received['facts']['public:preference']['value'],'我喜欢猫')
        self.assertEqual(received['recent'][0]['role'],'child')
        self.assertEqual(received['recent'][1]['role'],'played')
        self.assertTrue(self.peer.session.context()['heard'])
    async def test_rules_roles_cross_game_and_private_projection(self):
        self.make()
        self.model.next_plan.update(action='change',mode='adventure',rules='轮流飞行',roles=['猫船长'])
        self.model.extracted=[dict(key='role',start=0,end=3,value='猫船长')]
        await self.turn('猫船长带队')
        self.model.next_plan.update(mode='story')
        self.model.extracted=[]
        await self.turn('变成故事，角色和规则不变')
        self.assertEqual(self.peer.session.game['roles'],['猫船长'])
        self.assertEqual(self.peer.session.game['rules'],'轮流飞行')
        old_identity=self.peer.session.session
        self.model.next_plan.update(action='private',secrets={'answer':'私密'})
        await self.turn('我想聊私事')
        shared=self.peer.session.context(shared=True)
        self.assertEqual(self.peer.session.session,old_identity)
        self.assertNotIn('我想聊私事',str(shared)); self.assertNotIn('私密',str(shared))
        self.model.next_plan.update(action='handoff',mode='chat',roles=[],rules='',secrets={})
        old_session=self.peer.session
        old_ack=self.peer.ack_identity
        await self.turn('换一个人单独玩')
        self.assertFalse(old_session.active)
        self.assertNotEqual(old_session.session,self.peer.session.session)
        self.assertFalse(self.peer.session.accept(old_ack))
        self.assertEqual(old_session.recent,[])
        self.assertEqual(old_session.facts,{})
        self.assertNotIn('猫船长',str(self.peer.session.context()))
    async def test_unplayed_story_cannot_commit_rules_or_heard(self):
        self.make(); self.socket.acknowledge=False
        self.model.next_plan.update(action='change',rules='尚未播放的剧情')
        p=self.peer;p.session.begin_turn();p.session.drain_commands()
        p.generation=asyncio.create_task(p.respond('讲故事',0))
        await p.handle(json.dumps(dict(v=2,type='bind',epoch=0,seq=0,player='p')))
        for _ in range(20):
            if p.session.pending: break
            await asyncio.sleep(.001)
        p.session.interrupt();p.epoch+=1;await p.cancel_generation()
        self.assertEqual(p.session.context()['heard'],())
        self.assertEqual(p.session.game,{})
    async def test_long_chat_over_128_segments_and_64k_cumulative(self):
        self.make()
        self.model.extracted=[dict(key='preference',start=0,end=4,value='我喜欢猫')]
        await self.turn('我喜欢猫')
        self.model.extracted=[]
        total=0; output_bytes=0
        for n in range(160):
            self.model.next_plan['sentences']=[f'第{n}颗星球，'+'星球旅行背景，'*13, f'第{n}个伙伴，'+'故事继续向前，'*13]
            output_bytes+=sum(len(v.encode()) for v in self.model.next_plan['sentences'])
            self.model.next_plan['anchors']={f'plot.{n}':0}
            text=f'第{n}轮，'+ '星球旅行背景，'*60
            total+=len(text.encode())
            await self.turn(text)
        self.assertGreater(total,65536)
        self.assertGreater(output_bytes,65536)
        self.assertLess(len(self.peer.session.public),80)
        self.assertTrue(any('索引' in i for i,d in self.model.requests))
        self.assertEqual(self.peer.session.facts['public:preference']['value'],'我喜欢猫')
        self.assertTrue(self.peer.session._fits())
        self.assertLessEqual(sum(':played:' in k for k in self.peer.session.facts),16)
    async def test_private_scope_compaction_and_return_to_shared_cannot_leak(self):
        self.make()
        self.model.next_plan.update(action='private',sentences=['这是一段私事回应。'])
        await self.turn('合成私事')
        for n in range(100):
            self.model.next_plan['sentences']=[f'第{n}段私密故事。']
            await self.turn(f'私事{n}')
        self.assertLess(len(self.peer.session.private),80)
        self.model.next_plan.update(action='change',mode='story',sentences=['公开故事开始。'])
        await self.turn('回到公开故事')
        context=self.peer.session.context()
        self.assertEqual(context['private'],())
        self.assertNotIn('私事',str(context['recent']))
        self.assertNotIn('私密故事',str(context['heard']))

    async def test_safety_negative_control_prevents_any_audio(self):
        self.make();self.model.allowed=False
        p=self.peer;p.session.begin_turn();p.session.drain_commands()
        p.generation=asyncio.create_task(p.respond('合成危险请求',0))
        await p.handle(json.dumps(dict(v=2,type='bind',epoch=0,seq=0,player='p')))
        await p.generation
        self.assertFalse(any(e['type']=='audio' for e in self.socket.events))
        self.assertTrue(any(e['type']=='failure' for e in self.socket.events))
    async def test_solo_original_capture_budget_cannot_be_renewed_by_duplicate_or_heartbeat(self):
        self.make();now=[10.0]
        self.peer=VoicePeer(self.socket,self.providers,CompanionPolicy(),clock=lambda:now[0])
        self.socket.peer=self.peer
        await self.peer.handle(json.dumps(dict(v=2,type='wake_solo',epoch=0,seq=0,age_ms=6000)))
        self.assertEqual(self.peer.prepared[1],19)
        now[0]=14
        await self.peer.handle(json.dumps(dict(v=2,type='wake_solo',epoch=0,seq=1,age_ms=0)))
        await self.peer.handle(json.dumps(dict(v=2,type='heartbeat',epoch=0,seq=2)))
        self.assertEqual(self.peer.prepared[1],19)
        self.assertEqual(self.peer.input_budget.deadline,19)

    async def test_late_model_failure_cannot_revoke_new_participant(self):
        self.make()
        entered=asyncio.Event();release=asyncio.Event()
        async def delayed_plan(text,context):
            entered.set();await release.wait();raise ModelError('plan')
        self.providers.plan=delayed_plan
        p=self.peer;p.session.begin_turn();p.session.drain_commands()
        task=asyncio.create_task(p.respond('旧参与者',0));p.generation=task
        await p.handle(json.dumps(dict(v=2,type='bind',epoch=0,seq=0,player='old')))
        await entered.wait()
        old=p.session;old.handoff();p.session=Session(old.clock);p.session.begin_turn()
        p.epoch+=1
        output=p.session.output
        release.set();await task
        self.assertTrue(p.session.active);self.assertEqual(p.session.output,output)
        self.assertFalse(any(e['type']=='failure' for e in self.socket.events))

    async def test_supplier_failure_classification_does_not_infer_quota_from_429(self):
        cases=[(403,'insufficient_quota','quota'),(429,'rate_limit_exceeded','voice'),
               (429,None,'voice'),(503,'private-untrusted-body','voice'),
               ('network',None,'network'),('timeout',None,'timeout')]
        for status,code,expected in cases:
            async def response(req):
                if status=='network': raise httpx.ConnectError('sensitive source',request=req)
                if status=='timeout': raise httpx.ReadTimeout('sensitive source',request=req)
                return httpx.Response(status,json=dict(error=dict(code=code,message='sensitive body')))
            async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
                speech=DashScope(http,workspace='synthetic',region='cn-beijing',key='fake',
                    asr='fake',llm='deepseek-v4.1-flash-1017',tts='fake',voice='fake')
                model=DashScopeModel(speech)
                with self.assertRaises(VoiceFault) as error:
                    await model.complete('JSON',{})
                self.assertEqual(error.exception.code,expected)
                self.assertNotIn('sensitive',str(error.exception))
                self.assertEqual(model.usage['requests'],1)
                self.assertEqual(model.usage['failures'],1)
                self.assertNotIn('private-untrusted',str(model.last_code))

    async def test_actual_http_model_adapter_schema_and_usage(self):
        requests=[]
        async def respond(req):
            body=json.loads(req.content);requests.append(body)
            return httpx.Response(200,json=dict(choices=[dict(message=dict(content=json.dumps(
                dict(completion='complete',meaning='new_turn'))))],usage=dict(prompt_tokens=12,completion_tokens=9)))
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            speech=DashScope(http,workspace='synthetic',region='cn-beijing',key='fake',
                asr='fake',llm='deepseek-v4.1-flash-1017',tts='fake',voice='fake')
            model=DashScopeModel(speech);provider=UnifiedProviders(speech,model)
            result=await provider.endpoint('嗯',dict(heard=['你选小猫吗？']))
        self.assertEqual(result['meaning'],'new_turn')
        self.assertEqual(model.usage['prompt_tokens'],12)
        self.assertFalse(requests[0]['enable_thinking'])
        self.assertEqual(requests[0]['response_format'],dict(type='json_object'))

class Memory(unittest.TestCase):
    def fresh(self):
        self.now=0;s=Session(lambda:self.now);s.begin_turn();s.drain_commands();return s
    def test_summary_cannot_fabricate_delete_protected_or_write_after_cancel(self):
        s=self.fresh();s.public=[f'事实{i}' for i in range(40)]
        s.record_input('我喜欢猫',[dict(key='preference',start=0,end=4,value='我喜欢猫')])
        snap=s.memory_snapshot()
        self.assertFalse(s.compact(snap,[999]));self.assertEqual(len(s.public),40)
        self.assertTrue(s.compact(snap,[1,2]))
        self.assertEqual(s.facts['public:preference']['value'],'我喜欢猫')
        snap=s.memory_snapshot();s.interrupt()
        self.assertFalse(s.compact(snap,[1]))
    def test_source_propositions_survive_recent_window_for_negation_time_subject_and_question(self):
        for source in ('我不喜欢猫','以前喜欢猫','妹妹喜欢猫','我喜欢猫吗'):
            s=self.fresh();start=source.index('猫')
            s.record_input(source,[dict(key='preference',start=start,end=start+1,value='猫')])
            for n in range(20):s.record_input(f'背景{n}',[])
            item=s.context()['facts']['public:preference']
            self.assertEqual(item['source_text'],source)
            self.assertTrue(item['evidence_only'])
            self.assertNotIn(source,str(s.recent))
            s.public=[f'背景{i}' for i in range(50)]
            self.assertTrue(s.compact(s.memory_snapshot(),[]))
            self.assertEqual(s.facts['public:preference']['source_text'],source)

    def test_correction_and_two_preference_dimensions_keep_bounded_sources(self):
        s=self.fresh()
        for source in ('我喜欢猫','我喜欢蓝色','刚才说错了，我不喜欢猫，我喜欢狗'):
            s.turn+=1
            s.record_input(source,[dict(key='preference',start=0,end=len(source),value=source)])
        for n in range(20):s.record_input(f'背景{n}',[])
        from copy import deepcopy
        from backend.v2.memory import unpack
        expected={v['source_id']:deepcopy(v) for v in s.facts.values() if v.get('source')=='child'}
        sources=[f['source_text'] for k,f in s.facts.items() if k.startswith('public:preference')]
        self.assertIn('我喜欢蓝色',sources)
        self.assertIn('我喜欢猫',sources)
        self.assertIn('刚才说错了，我不喜欢猫，我喜欢狗',sources)
        for n in range(40):
            s.turn+=1;source=f'我喜欢第{n}种颜色'
            self.assertTrue(s.record_input(source,[dict(key='preference',start=0,end=len(source),value=source)]))
            expected[s.facts['public:preference']['source_id']]=deepcopy(s.facts['public:preference'])
        cold=unpack(s.source_archive)
        all_records=list(s.facts.items())+list(cold.values())
        self.assertEqual(len(all_records),43)
        self.assertEqual(len({v['source_id'] for k,v in all_records}),43)
        self.assertEqual({v['source_id']:v for k,v in all_records},expected)
        self.assertFalse({v['source_id'] for v in s.facts.values()} & set(cold))
        cat=s.context(query='猫')['facts']
        self.assertIn('我喜欢猫',[v['source_text'] for v in cat.values()])
        self.assertIn('刚才说错了，我不喜欢猫，我喜欢狗',[v['source_text'] for v in cat.values()])
        self.assertIn('我喜欢蓝色',[v['source_text'] for v in s.context(query='蓝色')['facts'].values()])
        self.assertTrue(all(v['evidence_only'] for v in cat.values()))
        self.assertTrue(s._fits())

    def test_private_proposition_sources_not_in_shared_projection(self):
        s=self.fresh();s.private_mode=True
        s.record_input('妹妹不喜欢猫',[dict(key='preference',start=5,end=6,value='猫')])
        self.assertNotIn('妹妹',str(s.context(shared=True)))
        s.private_mode=False
        self.assertNotIn('妹妹',str(s.context()))
        s.handoff();self.assertEqual(s.facts,{})

    def test_current_played_clue_survives_background_anchor_eviction_and_summary(self):
        s=self.fresh();stream=s.bind_player('p');tx=s.task('tts');ack=s.task('ack')
        s.drain_commands()
        for n in range(90):
            key='clue.current' if n==0 else f'plot.history{n}'
            text='已播放关键线索：有条纹' if n==0 else f'背景{n}'
            self.assertTrue(s.send(replace(tx,sequence=n),name=f's{n}',public=text,end=n+1,
                                   approved=True,anchors=(key,)))
            self.assertTrue(s.ack(replace(ack,sequence=n),player='p',stream=stream,segment=f's{n}',head=n+1))
        self.assertEqual(s.facts['public:played:clue.current']['value'],'已播放关键线索：有条纹')
        self.assertTrue(s.compact(s.memory_snapshot(),[]))
        self.assertEqual(s.facts['public:played:clue.current']['source'],'played')
        self.assertLessEqual(len(s.facts),16)

    def test_new_memory_fields_share_capacity_and_input_update_is_atomic(self):
        from copy import deepcopy
        from backend.v2.memory import unpack
        s=self.fresh()
        for n in range(43):
            s.turn+=1;source=f'我喜欢第{n}种颜色'
            self.assertTrue(s.record_input(source,[dict(key='preference',start=0,end=len(source),value=source)]))
        self.assertTrue(s.source_archive)
        baseline=len(json.dumps(dict(public=s.public,private=s.private,game=s.game,secrets=s.secrets,
            recent=s.recent,facts=s.facts,source_archive=s.source_archive,memory_limited=s.memory_limited,
            pending=[]),ensure_ascii=False).encode())
        s.public=['x'*(s.content_limit-baseline-1024)]
        self.assertEqual(s.content_limit,65536);self.assertTrue(s._fits())
        before=deepcopy((s.facts,s.source_archive,s.memory_revision,list(s.public)))
        source='我喜欢合成海豚'
        self.assertFalse(s.record_input(source,[dict(key='preference',start=0,end=len(source),value=source)]))
        self.assertEqual((s.facts,s.source_archive,s.public),(before[0],before[1],before[3]))
        self.assertEqual(s.memory_revision,before[2]+1)
        self.assertTrue(s._fits());self.assertTrue(s.memory_limited)
        self.assertLessEqual(len(s.recent),8);self.assertEqual(s.recent[-1]['text'],source)
        self.assertTrue(s.context()['memory']['capacity_limited'])
        self.assertNotIn(source,[v['source_text'] for v in s.context()['facts'].values()])
        self.assertEqual(len(s.facts)+len(unpack(s.source_archive)),43)
        atomic=deepcopy((s.facts,s.source_archive,s.recent,s.memory_revision,s.memory_limited))
        with self.assertRaises(ValueError):
            s.record_input(source,[dict(key='preference',start=0,end=len(source),value=source),
                                   dict(key='plot',start=0,end=1,value='不存在的来源')])
        self.assertEqual((s.facts,s.source_archive,s.recent,s.memory_revision,s.memory_limited),atomic)
        self.assertFalse(s._fits(recent=[dict(text='x'*65536)]))
        self.assertFalse(s._fits(facts={'bad':'x'*65536}))

    def test_fabricated_fact_rejected_atomically_and_private_cleared_on_expiry(self):
        s=self.fresh()
        with self.assertRaises(ValueError):
            s.record_input('猫',[dict(key='preference',start=0,end=1,value='狗')])
        self.assertEqual(s.facts,{})
        s.record_input('猫',[]);s.private_mode=True;s.remember_private('私事')
        self.now=600;s.poll()
        self.assertFalse(s.active);self.assertEqual(s.recent,[]);self.assertEqual(s.facts,{})
