"""Actual VoicePeer barriers, real UnifiedProviders validation, synthetic inference."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import time
import unittest
from unittest.mock import patch
from backend.v2.companion import UnifiedProviders
from backend.v2.voice import VoiceFault
from scripts import v2_multiturn_probe as probe
from tests.v2 import test_multiturn_probe as fixtures
from tests.v2.test_m05 import Model,plan

class Speech:
    def __init__(self):self.texts=[];self.before=None
    @asynccontextmanager
    async def synthesize(self,text,rate):
        if self.before:self.before()
        self.texts.append(text)
        async def frames():yield b'\x01\x00'*4800
        yield frames()

class Controlled(Model):
    def __init__(self):
        super().__init__(plan());self.next_plan.update(mode='story',rules='轮流编故事',roles=['小猫'],anchors={},sentences=['第一句。','第二句。'])
        self.plan_enter=asyncio.Event();self.fact_enter=asyncio.Event();self.plan_done=asyncio.Event();self.fact_done=asyncio.Event()
        self.plan_gate=None;self.fact_gate=None;self.serial=False;self.delay=False;self.trace=[];self.inputs=[];self.bad=False
        self.cancelled=False;self.stubborn=False;self.plan_count=0;self.fact_count=0;self.replan=False;self.fail_plan=False;self.fail_fact=False;self.plan_hook=None
    async def complete(self,instruction,data,*,schema=None):
        props=(schema or {}).get('properties',{})
        if 'mode' in props:
            self.plan_count+=1;self.plan_enter.set();self.trace.append('plan_start')
            if self.plan_hook:self.plan_hook()
            if self.plan_gate:await self.plan_gate.wait()
            if self.delay:await asyncio.sleep(.08)
            if self.fail_plan and self.plan_count==1:raise VoiceFault('network')
            if self.replan:self.next_plan['action']='change' if self.plan_count==1 else 'continue'
            value=await super().complete(instruction,data,schema=schema)
            self.trace.append('plan_end');self.plan_done.set();return value
        if 'facts' in props:
            self.fact_count+=1;self.fact_enter.set();self.inputs.append(deepcopy(data))
            if self.serial:await self.plan_done.wait()
            self.trace.append('facts_start')
            try:
                if self.fact_gate:
                    while not self.fact_gate.is_set():
                        try:await self.fact_gate.wait()
                        except asyncio.CancelledError:
                            self.cancelled=True
                            if not self.stubborn:raise
                if self.delay:await asyncio.sleep(.06)
                if self.fail_fact and self.fact_count==1:raise VoiceFault('network')
                self.extracted=[{'key':'rule','value':'FORGED' if self.bad else data['text']}]
                return await super().complete(instruction,data,schema=schema)
            finally:self.trace.append('facts_end');self.fact_done.set()
        self.trace.append('safe')
        return await super().complete(instruction,data,schema=schema)

class Prefetch(unittest.IsolatedAsyncioTestCase):
    async def start(self,model,*,private=False,old=False,observer=None,capacity=False):
        speech=Speech();p=UnifiedProviders(speech,model);peers=[];real=probe.VoicePeer
        class Peer(real):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs);peers.append(self);self.input_budget.speech(0)
                self.session.private_mode=private
                if old:self.session.record_input('旧来源',[])
                if capacity:
                    self.session.record_input('旧来源',[{'key':'clue','value':'旧来源','start':0,'end':3}])
                    fits=self.session._fits
                    self.session._fits=lambda **changes:False if 'facts' in changes else fits(**changes)
        async def run():
            with patch.object(probe,'VoicePeer',Peer):return await probe.run_case(fixtures.CASE,p,observer=observer)
        task=asyncio.create_task(run());await model.plan_enter.wait()
        return task,p,speech,peers

    async def test_facts_finishes_before_plan_but_cannot_commit_or_tts_until_original_gate(self):
        m=Controlled();m.plan_gate=asyncio.Event()
        task,p,speech,peers=await self.start(m)
        await m.fact_done.wait()
        self.assertEqual(peers[0].session.facts,{});self.assertEqual(peers[0].session.recent,[]);self.assertEqual(speech.texts,[])
        m.plan_gate.set();r=await task
        self.assertTrue(all(all(t['checks'].values()) for t in r['turns']))
        self.assertEqual(m.inputs,[{'text':t['input']} for t in fixtures.CASE['turns']])

    async def test_actual_voicepeer_delay_dependency_contrast_and_identical_fact_inputs(self):
        outputs=[];inputs=[]
        for serial in (True,False):
            m=Controlled();m.serial=serial;m.delay=True
            task,p,speech,peers=await self.start(m);r=await task
            self.assertTrue(all(all(t['checks'].values()) for t in r['turns']))
            outputs.append(r['turns'][0]['first_audio_after_text_ms']);inputs.append(m.inputs)
        self.assertEqual(inputs[0],inputs[1]);self.assertGreater(outputs[0]-outputs[1],35)
        print(json.dumps({'synthetic_serial_dependency_first_audio_ms':outputs[0],'synthetic_overlapped_first_audio_ms':outputs[1],'not_cloud_latency':True}))

    async def test_private_transition_commits_only_private_current_input(self):
        m=Controlled();m.next_plan['action']='private';snapshots=[]
        task,p,_,peers=await self.start(m,observer=lambda label,s:snapshots.append(s))
        await task
        self.assertTrue(snapshots[0]['facts']);self.assertTrue(all(v['private'] for v in snapshots[0]['facts'].values()))
        self.assertEqual(len(m.inputs),1);self.assertEqual(m.inputs[0],{'text':fixtures.CASE['turns'][0]['input']})

    async def test_existing_private_replan_does_not_prefetch_across_projection(self):
        m=Controlled();m.replan=True
        task,p,_,peers=await self.start(m,private=True,old=True)
        await task
        self.assertGreaterEqual(m.trace.index('facts_start'),m.trace.index('plan_end')+1)
        self.assertEqual(m.trace[:5],['plan_start','plan_end','plan_start','plan_end','facts_start'])
        self.assertTrue(all(set(x)=={'text'} for x in m.inputs));self.assertNotIn('旧来源',str(m.inputs))

    async def test_end_discards_and_confirms_prefetch_before_goodbye_tts(self):
        m=Controlled();m.next_plan['action']='end';m.fact_gate=asyncio.Event();m.plan_gate=asyncio.Event()
        task,p,speech,peers=await self.start(m);await m.fact_enter.wait()
        speech.before=lambda:self.assertTrue(m.cancelled)
        m.plan_gate.set();await task
        self.assertTrue(m.cancelled);self.assertTrue(speech.texts);self.assertFalse(peers[0].retired_tasks)

    async def test_handoff_cancels_prefetch_without_new_session_fact_or_audio(self):
        m=Controlled();m.next_plan['action']='handoff';m.fact_gate=asyncio.Event();m.plan_gate=asyncio.Event()
        task,p,speech,peers=await self.start(m,old=True);await m.fact_enter.wait();m.plan_gate.set();await task
        self.assertTrue(m.cancelled);self.assertEqual(speech.texts,[]);self.assertEqual(peers[0].session.facts,{})

    async def test_revision_change_discards_finished_facts_without_commit(self):
        m=Controlled();m.plan_gate=asyncio.Event()
        task,p,speech,peers=await self.start(m);await m.fact_done.wait();peers[0].revision+=1;m.plan_gate.set();await task
        self.assertEqual(speech.texts,[]);self.assertEqual(peers[0].session.facts,{})

    async def test_invalid_fact_provenance_never_reaches_review_tts_or_storage(self):
        m=Controlled();m.bad=True
        task,p,speech,peers=await self.start(m);await task
        self.assertEqual(speech.texts,[]);self.assertEqual(peers[0].session.facts,{})
        self.assertNotIn('safe',m.trace)

    async def test_parallel_read_failures_share_one_retry_reservation(self):
        m=Controlled();m.fail_plan=True;m.fail_fact=True
        task,p,speech,peers=await self.start(m)
        original_budget=peers[0].input_budget
        await task
        self.assertLessEqual(m.plan_count+m.fact_count,3);self.assertEqual(speech.texts,[])
        # Fixed local help disarms the failed input; inspect the actual shared
        # reservation, not the fresh budget installed after scope revocation.
        self.assertEqual(original_budget.read_retry_revision,0)

    async def test_cancel_stubborn_prefetch_is_bounded_retained_and_cannot_publish(self):
        m=Controlled();m.fact_gate=asyncio.Event();m.stubborn=True
        task,p,speech,peers=await self.start(m);await m.fact_enter.wait()
        try:
            peers[0].generation.cancel()
            done,_=await asyncio.wait({task},timeout=.9);self.assertTrue(done)
            with self.assertRaises(asyncio.CancelledError):await task
            self.assertTrue(peers[0].quarantined);self.assertEqual(speech.texts,[])
            self.assertTrue(p.probe_cleanup_handle.pending())
        finally:
            m.fact_gate.set()
            await asyncio.gather(*p.probe_cleanup_handle.pending(),return_exceptions=True)
        self.assertEqual(peers[0].session.facts,{})
        self.assertFalse(peers[0].generation_scopes)

    async def test_capacity_rejection_preserves_old_evidence_and_reviews_fallback_before_tts(self):
        m=Controlled();snapshots=[]
        task,p,speech,peers=await self.start(m,capacity=True,observer=lambda label,s:snapshots.append(s))
        await task
        self.assertTrue(snapshots[0]['memory']['capacity_limited'])
        self.assertTrue(snapshots[0]['facts'])
        self.assertTrue(all(f['source_text']=='旧来源' for f in snapshots[0]['facts'].values()))
        self.assertEqual(speech.texts,['我这会儿记不全前面的细节，请再告诉我这次最重要的事，我们接着玩。'])
        self.assertIn('safe',m.trace)

    async def test_invalid_plan_retires_pending_fact_read_without_publication(self):
        m=Controlled();m.next_plan['action']='INVALID';m.fact_gate=asyncio.Event();m.plan_gate=asyncio.Event()
        task,p,speech,peers=await self.start(m);await m.fact_enter.wait();m.plan_gate.set();await task
        self.assertTrue(m.cancelled);self.assertEqual(speech.texts,[])
        self.assertFalse(peers[0].retired_tasks);self.assertFalse(peers[0].generation_scopes)

    async def test_epoch_revoke_discards_finished_prefetch(self):
        m=Controlled();m.plan_gate=asyncio.Event()
        task,p,speech,peers=await self.start(m);await m.fact_done.wait();peers[0].epoch+=1;m.plan_gate.set();await task
        self.assertEqual(speech.texts,[]);self.assertEqual(peers[0].session.facts,{})

    async def test_revision_revoked_before_prefetch_task_starts_makes_no_fact_request(self):
        m=Controlled();m.plan_gate=asyncio.Event();real=probe.VoicePeer;peers=[]
        class Peer(real):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs);peers.append(self)
                m.plan_hook=lambda:setattr(self,'revision',self.revision+1)
        p=UnifiedProviders(Speech(),m)
        with patch.object(probe,'VoicePeer',Peer):
            task=asyncio.create_task(probe.run_case(fixtures.CASE,p))
            await m.plan_enter.wait();await asyncio.sleep(0);m.plan_gate.set();await task
        self.assertEqual(m.inputs,[]);self.assertEqual(p.speech.texts,[])
        self.assertEqual(peers[0].session.facts,{})
