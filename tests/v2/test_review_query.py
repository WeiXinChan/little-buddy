"""Synthetic fixtures; production VoicePeer/Session/strict model adapter and ACK."""
import asyncio,copy,json,unittest
from unittest.mock import patch
from backend.v2.memory import unpack
from backend.v2.session import Session
from backend.v2.voice import Operation,StaleOperation
from tests.v2 import test_m05 as old

SOURCE='我不喜欢薄荷味饼干，我喜欢南瓜饼干。'
QUERY='我很早说过不喜欢哪种饼干、喜欢哪种？'
def seed(s):
    for n in range(70):
        s.begin_turn();s.drain_commands()
        text=SOURCE if n==0 else f'我喜欢第{n}种云朵图案'
        s.record_input(text,[dict(key='preference',value=text,start=0,end=len(text))])
    sid=next(v['source_id'] for _,v in unpack(s.source_archive).values() if v['source_text']==SOURCE)
    s.public.extend(f'合成背景{n}' for n in range(30))
    assert s.compact(s.memory_snapshot(),[])
    assert SOURCE not in str([s.facts,s.recent,s.public])
    return sid

class ColdModel(old.Model):
    def __init__(self,sid):
        super().__init__(old.plan());self.sid=sid;self.contexts=[]
        self.next_plan['sentences']=['你不喜欢薄荷味饼干。','你喜欢南瓜饼干。']
    async def complete(self,instruction,data,*,schema=None):
        props=(schema or {}).get('properties',{})
        if 'mode' in props or 'allow' in props:
            stage='plan' if 'mode' in props else 'review'
            self.contexts.append((stage,copy.deepcopy(data['context'])))
            if stage=='review':
                valid=any(v.get('source_id')==self.sid and v.get('source_text')==SOURCE for v in data['context']['facts'].values())
                return json.dumps(dict(allow=True,quality=valid))
        return await super().complete(instruction,data,schema=schema)

class ReviewQuery(unittest.IsolatedAsyncioTestCase):
    make=old.Integration.make
    turn=old.Integration.turn
    async def test_cold_basis_reaches_plan_whole_segments_and_final_ack(self):
        self.make();s=self.peer.session;sid=seed(s);model=ColdModel(sid);self.peer.providers.model=model
        original_session=s.session
        await self.turn(QUERY)
        self.assertEqual(s.session,original_session)
        self.assertEqual([stage for stage,_ in model.contexts],['plan','review','review','review'])
        for stage,c in model.contexts:
            self.assertTrue(any(v.get('source_id')==sid for v in c['facts'].values()),stage)
        self.assertEqual(s.public[-2:],model.next_plan['sentences'])
        self.assertFalse(s.pending);self.assertEqual(s.game['mode'],'chat')
        self.assertIn(sid,unpack(s.source_archive));self.assertNotIn(sid,{v.get('source_id') for v in s.facts.values()})
    async def test_review_reprojects_latest_fact_commit_not_plan_snapshot(self):
        self.make();sid=seed(self.peer.session)
        class Added(ColdModel):
            async def complete(inner,instruction,data,*,schema=None):
                if 'facts' in (schema or {}).get('properties',{}):
                    return json.dumps(dict(facts=[dict(key='clue',value=QUERY)]))
                return await super().complete(instruction,data,schema=schema)
        m=Added(sid);self.peer.providers.model=m;await self.turn(QUERY)
        self.assertFalse(any(v.get('source_text')==QUERY for v in m.contexts[0][1]['facts'].values()))
        self.assertTrue(all(any(v.get('source_text')==QUERY for v in c['facts'].values()) for stage,c in m.contexts if stage=='review'))
    async def test_missing_source_not_filled_or_allowed(self):
        self.make();model=ColdModel('NONEXISTENT_SOURCE');self.peer.providers.model=model
        p=self.peer;p.session.begin_turn();p.session.drain_commands()
        p.generation=asyncio.create_task(p.respond(QUERY,p.epoch))
        await p.handle(json.dumps(dict(v=2,type='bind',epoch=p.epoch,seq=0,player='synthetic')));await p.generation
        self.assertFalse(p.session.public);self.assertFalse(p.session.game)
        self.assertTrue(any(e.get('code')=='voice' for e in self.socket.events))
        self.assertFalse(any(e['type']=='audio' for e in self.socket.events))
    async def test_stale_owner_cannot_even_project_or_call_review(self):
        for change in ('epoch','revision','session','cancelled','expired'):
            self.make();p=self.peer;op=Operation(p,p.epoch,p.revision)
            if change=='epoch':p.epoch+=1
            elif change=='revision':p.revision+=1
            elif change=='session':p.session=Session(op.session.clock)
            elif change=='cancelled':op.cancelled=True
            else:op.session.expires=op.session.clock()-1
            with patch.object(op.session,'context',side_effect=AssertionError('stale_projection')):
                with self.assertRaises(StaleOperation):await p.review(op,'待审句',query=QUERY)
            self.assertFalse(self.model.requests)
    async def test_shared_projection_never_copies_private_evidence(self):
        self.make();s=self.peer.session;s.private_mode=True
        private='PRIVATE_CANARY饼干';s.record_input(private,[dict(key='preference',value=private,start=0,end=len(private))])
        s.private.append(private);s.private_mode=False
        await self.peer.review(Operation(self.peer,self.peer.epoch),'公开合成句',query='饼干')
        self.assertNotIn('PRIVATE_CANARY',str(self.model.requests))
    async def test_cancelled_review_result_cannot_publish(self):
        self.make();p=self.peer;entered=asyncio.Event();release=asyncio.Event()
        async def review(*a):entered.set();await release.wait();return True
        p.providers.review=review;op=Operation(p,p.epoch)
        task=asyncio.create_task(p.review(op,'合成句',query=QUERY));await entered.wait();p.epoch+=1;release.set()
        with self.assertRaises(StaleOperation):await task
        self.assertFalse(p.session.public);self.assertFalse(p.session.pending)
