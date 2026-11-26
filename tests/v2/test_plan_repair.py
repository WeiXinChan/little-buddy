"""Bounded full replanning through actual VoicePeer; no cloud/semantic proof."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from backend.v2.companion import UnifiedProviders,ModelError,CompanionPolicy
from backend.v2.voice import VoicePeer,VoiceFault,Operation,StaleOperation
from tests.v2 import test_m05 as fixture
from scripts import v2_multiturn_probe as probe

class RepairModel(fixture.Model):
    def __init__(self,*,always_bad=False,deny=False):
        super().__init__(fixture.plan());self.plan_calls=0;self.fact_calls=0;self.always_bad=always_bad;self.allowed=not deny
        self.entered=asyncio.Event();self.release=None;self.mutate=False;self.fact_seen=asyncio.Event();self.require_fact_start=False;self.promise=False
    async def complete(self,instruction,data,*,schema=None):
        if '提取孩子' in instruction:self.fact_calls+=1;self.fact_seen.set()
        if '严格字段' in instruction:
            self.plan_calls+=1;self.requests.append((instruction,deepcopy(data)))
            if self.require_fact_start:await self.fact_seen.wait()
            if data.get('server_constraints',{}).get('correction'):
                self.entered.set()
                if self.release:await self.release.wait()
            value=fixture.plan();value.update(mode='story',rules='模型改写过的故事规则',anchors={})
            value['sentences']=['CANDIDATE_ONLY。','不得发回模型的无效句。'] if self.always_bad or self.plan_calls==1 else ['小猫慢慢飞向蓝色星星。']
            if self.promise:value['rules']='轮流编故事，一人接一句' if self.plan_calls==1 else '模型擅自改写每人两句'
            if self.mutate:data['context']['game']={'rules':'POISON'}
            return json.dumps(value,ensure_ascii=False)
        return await super().complete(instruction,data,schema=schema)

class Repair(unittest.IsolatedAsyncioTestCase):
    def make(self,model):
        self.socket=fixture.Socket();self.providers=UnifiedProviders(fixture.Speech(),model)
        self.peer=VoicePeer(self.socket,self.providers,CompanionPolicy());self.socket.peer=self.peer
        self.peer.input_budget.speech();self.peer.session.game={'mode':'story','rules':'模型可改写','roles':[],'turn_limit':1}
        self.addAsyncCleanup(self.cleanup,self.peer)
    async def cleanup(self,peer):await peer.cancel_generation();peer.session.clear()
    async def start(self,text='接着讲。'):
        p=self.peer;p.session.begin_turn();p.session.drain_commands()
        p.generation=asyncio.create_task(p.respond(text,p.epoch))
        await p.handle(json.dumps(dict(v=2,type='bind',epoch=p.epoch,seq=p.sequence+1,player='test')))
        return p.generation
    async def test_success_sends_first_bound_once_replans_same_snapshot_without_bad_candidate(self):
        m=RepairModel();m.mutate=True;self.make(m);original=self.peer.input_budget;deadline=original.deadline
        task=await self.start();await task
        self.assertEqual(m.plan_calls,2);self.assertEqual(m.fact_calls,1)
        self.assertIs(self.peer.input_budget,original);self.assertEqual(original.deadline,deadline)
        self.assertEqual(original.read_retry_revision,self.peer.revision)
        requests=[d for i,d in m.requests if '严格字段' in i]
        self.assertEqual(requests[0]['server_constraints'],{'story_sentences_max':1,'correction':None})
        self.assertEqual(requests[1]['server_constraints'],{'story_sentences_max':1,'correction':'plan_sentence_limit'})
        self.assertEqual(requests[0]['context'],requests[1]['context'])
        self.assertNotIn('CANDIDATE_ONLY',json.dumps(requests,ensure_ascii=False));self.assertNotIn('POISON',json.dumps(requests))
        self.assertEqual(self.peer.session.public,['小猫慢慢飞向蓝色星星。']);self.assertEqual(self.peer.session.game['turn_limit'],1)

    async def test_initial_model_promise_count_can_correct_without_sending_invalid_proposal(self):
        m=RepairModel();m.promise=True;self.make(m);self.peer.session.game={}
        await (await self.start('轮流编小猫坐飞船的故事，我先说小猫出发。'))
        requests=[d for i,d in m.requests if '严格字段' in i]
        self.assertIsNone(requests[0]['server_constraints']['story_sentences_max'])
        self.assertEqual(requests[1]['server_constraints']['story_sentences_max'],1)
        self.assertEqual(requests[0]['context'],requests[1]['context'])
        self.assertNotIn('CANDIDATE_ONLY',json.dumps(requests))
        self.assertEqual(self.peer.session.game['turn_limit'],1)
        self.assertEqual(self.peer.session.public,['小猫慢慢飞向蓝色星星。'])

    async def test_second_bad_plan_is_terminal_no_tts_and_facts_not_duplicated(self):
        m=RepairModel(always_bad=True);m.require_fact_start=True;self.make(m);before=deepcopy(self.peer.session.game)
        await (await self.start())
        self.assertEqual((m.plan_calls,m.fact_calls),(2,1));self.assertEqual(self.peer.session.game,before)
        self.assertFalse(self.peer.session.public);self.assertFalse(any(e['type']=='audio' for e in self.socket.events))
        self.assertEqual(self.peer.last_failure['contract'],'plan_sentence_limit')

    async def test_repaired_plan_still_needs_safety_and_full_ack(self):
        m=RepairModel(deny=True);self.make(m);await (await self.start())
        self.assertEqual(m.plan_calls,2);self.assertFalse(any(e['type']=='audio' for e in self.socket.events))
        self.assertFalse(self.peer.session.public)
        m=RepairModel();self.make(m);self.socket.acknowledge=False
        task=await self.start()
        for _ in range(100):
            if self.peer.session.pending:break
            await asyncio.sleep(.001)
        self.assertTrue(self.peer.session.pending);self.assertFalse(self.peer.session.public)
        self.assertEqual(self.peer.session.game['rules'],'模型可改写')
        await self.peer.handle(json.dumps(dict(v=2,type='stop',epoch=1,seq=0,intent='cancel')))
        self.assertFalse(self.peer.session.public);self.assertEqual(self.peer.session.game['rules'],'模型可改写')

    async def test_cancel_or_new_revision_during_correction_cannot_publish_late_response(self):
        for change in ('revision','management','cancel'):
            m=RepairModel();m.release=asyncio.Event();self.make(m);task=await self.start();await m.entered.wait()
            if change=='revision':self.peer.revision+=1
            elif change=='management':self.peer.session.pause_management()
            else:task.cancel()
            m.release.set()
            try:await task
            except asyncio.CancelledError:pass
            self.assertFalse(self.peer.session.public);self.assertFalse(any(e['type']=='audio' for e in self.socket.events))
            self.assertEqual(m.plan_calls,2)

    async def test_consumed_retry_private_transition_and_pending_output_do_not_repair(self):
        for guard in ('consumed','private','transition','pending'):
            m=RepairModel();self.make(m);p=self.peer
            if guard=='consumed':p.input_budget.read_retry_revision=p.revision
            if guard=='private':p.session.private_mode=True
            if guard=='pending':p.session.response_confirmed=True
            context=p.session.context()
            with self.assertRaises(ModelError):await p.read_request(Operation(p,p.epoch),'plan','接着讲。',context,allow_plan_repair=guard!='transition')
            self.assertEqual(m.plan_calls,1)

    async def test_fact_retry_and_correction_share_atomic_single_reservation(self):
        m=RepairModel();self.make(m);p=self.peer;seen=[]
        async def facts(text):
            seen.append(text)
            if len(seen)==1:raise VoiceFault('network')
            return []
        p.providers.facts=facts
        await p.read_request(Operation(p,0),'facts','合成输入')
        with self.assertRaises(ModelError):await p.read_request(Operation(p,0),'plan','继续。',p.session.context())
        self.assertEqual(len(seen),2);self.assertEqual(m.plan_calls,1)
        # The opposite reservation order must also consume the same slot.
        m=RepairModel();self.make(m);p=self.peer;after=[]
        await p.read_request(Operation(p,0),'plan','继续。',p.session.context())
        async def failed_fact(text):after.append(text);raise VoiceFault('network')
        p.providers.facts=failed_fact
        with self.assertRaises(VoiceFault):await p.read_request(Operation(p,0),'facts','合成输入')
        self.assertEqual(len(after),1);self.assertEqual(m.plan_calls,2)

    async def test_unknown_plan_error_quota_and_expired_original_budget_do_not_expand_calls(self):
        for mode in ('structure','quota','expired'):
            m=RepairModel();self.make(m)
            if mode=='expired':self.peer.input_budget.anchor=self.peer.session.clock()-16
            elif mode=='quota':
                async def fail(*args,**kwargs):raise VoiceFault('quota')
                self.peer.providers.plan=fail
            else:m.next_plan['action']='bad'
            if mode=='structure':
                async def fail(*args,**kwargs):raise ModelError('plan')
                self.peer.providers.plan=fail
            with self.assertRaises((ModelError,VoiceFault,TimeoutError)):
                await self.peer.read_request(Operation(self.peer,0),'plan','继续。',self.peer.session.context())
            self.assertLessEqual(m.plan_calls,1)

    async def test_correction_quota_failure_and_forged_safety_tag_do_not_grant_another_attempt(self):
        class Quota(RepairModel):
            async def complete(self,instruction,data,*,schema=None):
                if '严格字段' in instruction and data.get('server_constraints',{}).get('correction'):
                    self.plan_calls+=1;raise VoiceFault('quota')
                return await super().complete(instruction,data,schema=schema)
        m=Quota();self.make(m);await (await self.start())
        self.assertEqual(m.plan_calls,2);self.assertFalse(any(e['type']=='audio' for e in self.socket.events))
        self.assertEqual(self.peer.input_budget.read_retry_revision,self.peer.revision)
        from backend.v2.diagnostics import mark_contract
        calls=[]
        async def denied(*args):raise mark_contract(VoiceFault('safety'),'plan_sentence_limit')
        async def wrong_repair(*args):calls.append(1);return {}
        self.peer.providers=SimpleNamespace(plan=denied,repair_plan=wrong_repair)
        with self.assertRaises(VoiceFault):await self.peer.read_request(Operation(self.peer,0),'plan','继续',{})
        self.assertFalse(calls)

    async def test_probe_anchors_each_synthetic_expression_and_repair_is_metered(self):
        m=RepairModel();p=UnifiedProviders(fixture.Speech(),m)
        case={'id':'repair-probe','turns':[{'label':str(i),'input':'我们每人一句，继续编故事。','expect':{'mode':'story','terms':[]}} for i in range(3)]}
        report=await probe.run_case(case,p)
        self.assertEqual(len(report['turns']),3);self.assertTrue(all(r['checks']['delivery'] for r in report['turns']))
        self.assertEqual(m.fact_calls,3);self.assertEqual(m.plan_calls,4)
        self.assertEqual(report['model_requests'],10) # 4 PLAN + 3 FACTS + 3 SAFE
