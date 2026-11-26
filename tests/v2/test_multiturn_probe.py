"""Harness trust/quality detectors, not evidence that a model played correctly."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import unittest
from backend.v2.companion import UnifiedProviders
from scripts.v2_multiturn_probe import run_case,judge,ModelMeter,ProbeLimit
from tests.v2.test_m05 import Model,Speech,plan

CASE={'id':'synthetic-harness','turns':[{'label':str(i),'input':text,'expect':{'mode':'story','terms':['轮流']}} for i,text in enumerate(('轮流编故事，我说小猫出发。','小猫发现月亮。','轮到你继续。'))]}

class Probe(unittest.IsolatedAsyncioTestCase):
    def providers(self):
        m=Model(plan());m.next_plan.update(mode='story',rules='轮流编故事',roles=['小猫'],anchors={})
        return UnifiedProviders(Speech(),m)
    async def test_real_voicepeer_progresses_context_from_actual_ack_not_expectations(self):
        p=self.providers();model=p.model;report=await run_case(CASE,p)
        self.assertEqual(len(report['turns']),3)
        self.assertTrue(all(all(t['checks'].values()) for t in report['turns']))
        plans=[d for i,d in model.requests if '严格字段' in i]
        self.assertEqual(len(plans),3)
        self.assertEqual(plans[0]['context']['game'],{})
        self.assertEqual(plans[1]['context']['game']['mode'],'story')
        self.assertTrue(plans[1]['context']['heard'])
        self.assertNotIn('expect',str(plans));self.assertNotIn('pcm',json.dumps(report))
        self.assertIs(p.model,model);self.assertFalse(report['p12_verified'] or report['p15_verified'])
    async def test_wrong_mode_stops_batch_instead_of_overwriting_context(self):
        p=self.providers();p.model.next_plan['mode']='guess'
        report=await run_case(CASE,p)
        self.assertEqual(len(report['turns']),1);self.assertFalse(report['turns'][0]['checks']['mode'])
    async def test_safety_rejection_never_counts_delivered_or_heard(self):
        p=self.providers();p.model.allowed=False
        report=await run_case(CASE,p)
        self.assertEqual(report['tts_requests'],0)
        self.assertFalse(report['turns'][0]['checks']['delivery'])
        self.assertFalse(report['turns'][0]['checks']['played_context'])
    async def test_rule_role_and_abandon_detectors_flag_mismatch(self):
        context={'game':{'mode':'adventure','rules':'继续闯关','roles':['向导']},'heard':['x']}
        checks=judge({'mode':'chat','terms':['船长']},context)
        self.assertFalse(checks['mode']);self.assertFalse(checks['rule_role_terms'])
        context['game']={'mode':'chat','rules':'','roles':[]}
        self.assertTrue(judge({'mode':'chat','terms':[]},context)['mode'])
    async def test_played_history_loss_or_unchanged_history_is_not_continuity(self):
        for heard in ([],['old']):
            checks=judge({'mode':'story','terms':[]},{'game':{'mode':'story'},'heard':heard},previous_heard=['old'])
            self.assertFalse(checks['played_context'])
    async def test_request_gate_counts_actual_retry_calls_and_rejects_before_io(self):
        model=Model(plan());meter=ModelMeter(model)
        for _ in range(24):await meter.complete('fixture',{},schema={})
        with self.assertRaises(ProbeLimit):await meter.complete('fixture',{},schema={})
        self.assertEqual(len(model.requests),24)
    async def test_image_configuration_or_oversized_case_cannot_run(self):
        p=self.providers();p.dynamic_images=object()
        with self.assertRaises(ProbeLimit):await run_case(CASE,p)
        p.dynamic_images=None;case=deepcopy(CASE);case['turns']*=2
        with self.assertRaises(ProbeLimit):await run_case(case,p)
    async def test_catalogue_covers_eight_topics_and_explicit_transition_targets(self):
        data=json.loads(Path('docs/testing/v2/multiturn/cases.json').read_text())
        self.assertEqual(len(data['cases']),12)
        self.assertTrue(all(len(c['turns'])==3 for c in data['cases']))
        for mode in ('guess','story','adventure','association'):
            self.assertGreaterEqual(sum(all(t['expect']['mode']==mode for t in c['turns']) for c in data['cases']),2)
        self.assertTrue({'cross-game','exchange-question','change-rules','abandon'}<={c['id'] for c in data['cases']})
    async def test_observer_receives_detached_immutable_actual_context_without_expected(self):
        p=self.providers();observations=[]
        def observer(label,snapshot):
            observations.append((label,snapshot))
            with self.assertRaises(TypeError):snapshot['game']['mode']='guess'
            self.assertNotIn('expect',snapshot)
        report=await run_case(CASE,p,observer=observer)
        self.assertEqual(len(observations),3);self.assertEqual(observations[0][1]['game']['mode'],'story')
        self.assertTrue(observations[0][1]['heard']) # snapshot survives Session.clear
        self.assertTrue(all(all(t['checks'].values()) for t in report['turns']))
        self.assertNotIn('我们一起玩吧',json.dumps(report,ensure_ascii=False))
    async def test_observer_exception_stops_before_next_turn_and_is_not_pass(self):
        p=self.providers()
        def observer(*args):raise RuntimeError('PRIVATE_OBSERVER_TEXT')
        report=await run_case(CASE,p,observer=observer)
        self.assertEqual(report['turns'],[{'label':'batch-stop','failure':'RuntimeError'}])
        self.assertEqual(len([d for i,d in p.model.requests if '严格字段' in i]),1)
        self.assertNotIn('PRIVATE_OBSERVER_TEXT',json.dumps(report))
    async def test_async_observer_is_rejected_without_running_its_body(self):
        ran=[]
        async def observer(*args):ran.append(True)
        report=await run_case(CASE,self.providers(),observer=observer)
        self.assertEqual(report['turns'][-1]['failure'],'ProbeLimit');self.assertEqual(ran,[])
    async def test_usage_is_batch_delta_with_missing_unknown_not_zero(self):
        from scripts.v2_multiturn_probe import usage_delta
        before={'usage':{'requests':100,'failures':2,'prompt_tokens':1000,'completion_tokens':100},'usage_missing':{'prompt_tokens':3,'completion_tokens':1}}
        after={'usage':{'requests':105,'failures':2,'prompt_tokens':1200,'completion_tokens':150},'usage_missing':{'prompt_tokens':3,'completion_tokens':2}}
        self.assertEqual(usage_delta(before,after),{'requests':5,'failures':0,'prompt_tokens':200,'completion_tokens':None})
        self.assertTrue(all(x is None for x in usage_delta({},{}).values()))
    async def test_run_report_excludes_provider_previous_usage(self):
        p=self.providers();model=p.model
        model.metrics=lambda:{'usage':{'requests':100+len(model.requests),'failures':7,'prompt_tokens':500+10*len(model.requests),'completion_tokens':200+len(model.requests)},'usage_missing':{'prompt_tokens':0,'completion_tokens':0}}
        report=await run_case(CASE,p)
        self.assertEqual(report['usage']['requests'],report['model_requests'])
        self.assertEqual(report['usage']['prompt_tokens'],10*report['model_requests'])
        self.assertEqual(report['usage']['failures'],0)
