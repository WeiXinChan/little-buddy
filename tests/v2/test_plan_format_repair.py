"""Actual VoicePeer single-reservation formatting repair; no cloud."""
import asyncio,json,unittest
from copy import deepcopy
from backend.v2.voice import VoiceFault,Operation
from backend.v2.companion import ModelError
from tests.v2 import test_plan_repair as prior
from tests.v2 import test_m05 as fixture

class FormatModel(fixture.Model):
    def __init__(self,always_bad=False,network=False):
        super().__init__(fixture.plan());self.calls=0;self.facts=0;self.always_bad=always_bad;self.network=network
        self.entered=asyncio.Event();self.release=None;self.fact_seen=asyncio.Event()
    async def complete(self,instruction,data,*,schema=None):
        if '提取孩子' in instruction:self.facts+=1;self.fact_seen.set()
        if '严格字段' in instruction:
            self.calls+=1;self.requests.append((instruction,deepcopy(data)))
            if self.always_bad:await self.fact_seen.wait()
            if self.network and self.calls==1:raise VoiceFault('network')
            correction=data.get('server_constraints',{}).get('correction')
            if correction=='plan_anchors':
                self.entered.set()
                if self.release:await self.release.wait()
            value=fixture.plan();value.update(mode='story',rules='每人一句',anchors={'plot.current':'INVALID_SECRET_CANARY'} if self.always_bad or self.calls==1 or self.network else {'plot.current':0},sentences=['小船顺着河流慢慢前进。'])
            return json.dumps(value,ensure_ascii=False)
        return await super().complete(instruction,data,schema=schema)

class Format(unittest.IsolatedAsyncioTestCase):
    make=prior.Repair.make
    cleanup=prior.Repair.cleanup
    start=prior.Repair.start
    async def test_one_complete_replan_same_payload_no_draft_and_original_budget(self):
        m=FormatModel();self.make(m);budget=self.peer.input_budget;deadline=budget.deadline
        await (await self.start())
        self.assertEqual((m.calls,m.facts),(2,1));self.assertEqual(budget.deadline,deadline)
        self.assertEqual(budget.read_retry_revision,self.peer.revision)
        plans=[d for i,d in m.requests if '严格字段' in i]
        self.assertEqual(plans[0]['context'],plans[1]['context']);self.assertEqual(plans[0]['text'],plans[1]['text'])
        self.assertEqual(plans[1]['server_constraints']['correction'],'plan_anchors')
        self.assertEqual(plans[1]['server_constraints']['format_detail'],'anchor_index_type')
        self.assertNotIn('INVALID_SECRET_CANARY',str(plans))
        self.assertEqual(self.peer.session.public,['小船顺着河流慢慢前进。'])
    async def test_second_invalid_plan_terminal_no_fact_repeat_or_publication(self):
        m=FormatModel(always_bad=True);self.make(m);before=deepcopy(self.peer.session.game)
        await (await self.start())
        self.assertEqual(m.calls,2);self.assertEqual(m.facts,1)
        self.assertEqual(self.peer.session.game,before);self.assertFalse(self.peer.session.public)
        self.assertEqual(self.peer.last_failure['contract'],'plan_anchors')
    async def test_network_and_format_share_one_slot_not_two(self):
        m=FormatModel(network=True);self.make(m)
        await (await self.start())
        self.assertEqual(m.calls,2);self.assertFalse(self.peer.session.public)
        self.assertEqual(self.peer.last_failure['contract'],'plan_anchors')
    async def test_private_replan_pending_or_consumed_never_admitted(self):
        for guard in ('private','transition','consumed','pending'):
            m=FormatModel();self.make(m);p=self.peer
            if guard=='private':p.session.private_mode=True;p.session.private.append('PRIVATE_CANARY')
            if guard=='consumed':p.input_budget.read_retry_revision=p.revision
            if guard=='pending':p.session.response_confirmed=True
            with self.assertRaises(ModelError):await p.read_request(Operation(p,p.epoch),'plan','接着讲。',p.session.context(),allow_plan_repair=guard!='transition')
            self.assertEqual(m.calls,1)
    async def test_late_repair_cancel_revision_or_expiry_cannot_commit(self):
        for change in ('cancel','revision','expiry'):
            m=FormatModel();m.release=asyncio.Event();self.make(m);task=await self.start();await m.entered.wait()
            if change=='cancel':task.cancel()
            elif change=='revision':self.peer.revision+=1
            else:
                b=self.peer.input_budget;b.clock=lambda:b.deadline+1
            m.release.set()
            try:await task
            except asyncio.CancelledError:pass
            self.assertFalse(self.peer.session.public);self.assertEqual(m.calls,2)
    async def test_repaired_proposal_still_requires_full_ack(self):
        m=FormatModel();self.make(m);self.socket.acknowledge=False;task=await self.start()
        async with asyncio.timeout(1):
            while not self.peer.session.pending:await asyncio.sleep(0)
        self.assertFalse(self.peer.session.public)
        self.peer.session.interrupt();await self.peer.cancel_generation()
        self.assertFalse(self.peer.session.public)
    async def test_nonwhitelist_code_and_secret_or_facts_do_not_use_port(self):
        m=FormatModel();self.make(m)
        for code,detail in [('plan_guess_answer_changed','anchor_index_type'),('fact_source_mismatch','anchor_index_type'),('plan_anchors','anchor_name'),('plan_anchors','unknown')]:
            with self.assertRaises(ModelError):await self.providers.repair_plan_format('合成',{},code=code,detail=detail)
        self.assertEqual(m.calls,0)
    async def test_format_then_sentence_failure_cannot_spend_second_repair(self):
        class SecondCount(FormatModel):
            async def complete(self,instruction,data,*,schema=None):
                raw=await super().complete(instruction,data,schema=schema)
                if '严格字段' in instruction and self.calls==2:
                    value=json.loads(raw);value['sentences']=['合成第一句。','合成第二句。'];return json.dumps(value,ensure_ascii=False)
                return raw
        m=SecondCount();self.make(m);await (await self.start())
        self.assertEqual(m.calls,2);self.assertFalse(self.peer.session.public)
        self.assertEqual(self.peer.last_failure['contract'],'plan_sentence_limit')
    async def test_boolean_and_out_of_range_have_exact_repair_constraint(self):
        for index,detail in [(True,'anchor_index_type'),(1,'anchor_index_range')]:
            class BadIndex(FormatModel):
                async def complete(self,instruction,data,*,schema=None):
                    raw=await super().complete(instruction,data,schema=schema)
                    if '严格字段' in instruction and self.calls==1:
                        value=json.loads(raw);value['anchors']={'plot.current':index};return json.dumps(value,ensure_ascii=False)
                    return raw
            m=BadIndex();self.make(m);await (await self.start())
            self.assertEqual(m.calls,2);self.assertTrue(self.peer.session.public)
            plans=[d for i,d in m.requests if '严格字段' in i]
            self.assertEqual(plans[-1]['server_constraints']['format_detail'],detail)
    async def test_nonstory_adventure_format_repair_is_not_story_only(self):
        class Adventure(FormatModel):
            async def complete(self,instruction,data,*,schema=None):
                raw=await super().complete(instruction,data,schema=schema)
                if '严格字段' in instruction:
                    value=json.loads(raw);value.update(mode='adventure',rules='孩子选路');return json.dumps(value,ensure_ascii=False)
                return raw
        m=Adventure();self.make(m);self.peer.session.game={}
        await (await self.start('海底探险，我来选路线。'))
        self.assertEqual(m.calls,2);self.assertEqual(self.peer.session.game['mode'],'adventure')
        requests=[(i,d) for i,d in m.requests if '严格字段' in i]
        self.assertEqual(requests[-1][1]['server_constraints']['format_detail'],'anchor_index_type')
        self.assertIn('其中仅story_sentences_max',requests[-1][0])
        self.assertIn('适用于非story模式',requests[-1][0])
