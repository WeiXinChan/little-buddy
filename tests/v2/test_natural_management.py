"""Production semantic/transport path. ASR/model values are explicit synthetic fixtures."""
import asyncio
from contextlib import asynccontextmanager
import json
import unittest
from backend.v2.companion import UnifiedProviders,CompanionPolicy
from backend.v2.voice import VoicePeer


class Speech:
    def __init__(self,text='能不能让我看看家长能调整的选项？'):
        self.text=text;self.bytes=0;self.recognitions=0;self.syntheses=0
    @asynccontextmanager
    async def recognize(self,rate):
        assert rate==16000;self.recognitions+=1;parent=self
        class Recognizer:
            async def write(self,pcm):parent.bytes+=len(pcm)
            async def finish(self):return parent.text
        yield Recognizer()
    @asynccontextmanager
    async def synthesize(self,*args):
        self.syntheses+=1;raise AssertionError('management must not dispatch TTS')
        yield


class Model:
    def __init__(self,meaning='management'):
        self.meaning=meaning;self.calls=[];self.started=None;self.release=None
    async def complete(self,instruction,data,*,schema=None):
        assert 'completion:' in instruction, 'management must not dispatch facts/plan/safety/TTS'
        assert 'management' in schema['properties']['meaning']['enum']
        self.calls.append(data)
        if self.started is not None:
            self.started.set();await self.release.wait()
        return json.dumps(dict(completion='complete',meaning=self.meaning))


class Socket:
    def __init__(self):self.events=[];self.after_scope=None
    async def send(self,raw):
        event=json.loads(raw);self.events.append(event)
        if event['type']=='scope' and self.after_scope is not None:self.after_scope()


class NaturalManagement(unittest.IsolatedAsyncioTestCase):
    async def make(self,meaning='management'):
        speech=Speech();model=Model(meaning);socket=Socket()
        peer=VoicePeer(socket,UnifiedProviders(speech,model),CompanionPolicy())
        return peer,socket,speech,model
    async def analyze(self,p):
        await p.handle(json.dumps(dict(v=2,type='advance',epoch=0,seq=0,revision=1)))
        await p.handle(json.dumps(dict(v=2,type='input',epoch=0,seq=1,pcm='AAAAAA==',speech=True)))
        await p.handle(json.dumps(dict(v=2,type='probe',epoch=0,seq=2,revision=1)))
        await p.recognition
    async def seal(self,p):
        await p.handle(json.dumps(dict(v=2,type='seal',epoch=p.epoch,seq=p.sequence+1,revision=p.revision)))
    async def test_first_spoken_intent_uses_real_asr_endpoint_and_scope_before_event(self):
        p,s,speech,model=await self.make();await self.analyze(p);await self.seal(p)
        kinds=[e['type'] for e in s.events]
        self.assertEqual(kinds[-2:],['scope','management'])
        scope,event=s.events[-2:]
        for key in ('session','turn','revision','epoch'):self.assertEqual(scope[key],event[key])
        self.assertEqual((scope['turn'],scope['revision']),(0,1))
        self.assertEqual(set(event),{'v','type','epoch','session','turn','revision'})
        self.assertGreater(speech.bytes,0);self.assertEqual(len(model.calls),1)
        self.assertEqual(speech.syntheses,0);self.assertEqual(p.session.context()['heard'],())
        self.assertFalse(any(k in kinds for k in ('open','bound','audio','reply_end')))
    async def test_quoted_story_management_is_a_normal_turn_not_a_page_request(self):
        p,s,speech,model=await self.make('new_turn');speech.text='故事里猫船长管理一座城，继续讲吧'
        await self.analyze(p);await self.seal(p)
        self.assertFalse(any(e['type']=='management' for e in s.events))
        self.assertEqual(s.events[-1]['meaning'],'new_turn')
    async def test_new_input_preempts_late_semantic_intent(self):
        p,s,speech,model=await self.make();model.started=asyncio.Event();model.release=asyncio.Event()
        await p.handle(json.dumps(dict(v=2,type='advance',epoch=0,seq=0,revision=1)))
        await p.handle(json.dumps(dict(v=2,type='input',epoch=0,seq=1,pcm='AAAAAA==',speech=True)))
        await p.handle(json.dumps(dict(v=2,type='probe',epoch=0,seq=2,revision=1)))
        await model.started.wait()
        await p.handle(json.dumps(dict(v=2,type='advance',epoch=0,seq=3,revision=2)))
        model.release.set();await p.recognition
        self.assertFalse(any(e['type']=='management' for e in s.events));self.assertIsNone(p.analysis)
    async def test_scope_send_reentry_cannot_borrow_new_revision_or_session(self):
        for change in ('revision','session'):
            p,s,_,_=await self.make();await self.analyze(p)
            def preempt():
                if change=='revision':p.revision+=1
                else:p.session.handoff()
            s.after_scope=preempt;await self.seal(p)
            self.assertFalse(any(e['type']=='management' for e in s.events))
    async def test_deadline_reached_after_scope_send_rejects_late_entry(self):
        p,s,_,_=await self.make();await self.analyze(p)
        deadline=p.input_budget.deadline
        p.session.heartbeat_deadline=deadline+1
        def expire():p.session.clock=lambda:deadline
        s.after_scope=expire;await self.seal(p)
        self.assertTrue(any(e['type']=='scope' for e in s.events))
        self.assertFalse(any(e['type']=='management' for e in s.events))

if __name__=='__main__':unittest.main()
