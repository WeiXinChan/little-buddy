import copy,json,unittest
from unittest.mock import patch
from scripts import v2_finite_probe as p
from tests.v2 import test_m05 as old
from backend.v2.companion import UnifiedProviders

class Finite(unittest.IsolatedAsyncioTestCase):
    async def test_default_disabled_single_case_and_pin(self):
        for name,cap in p.CAPS.items():
            with patch.object(p,'live',side_effect=AssertionError('no cloud')),patch.object(p,'verify',side_effect=AssertionError('no config')):
                self.assertEqual(p.main(['--case',name]),0)
            p.select(name);self.assertEqual(p.base.LIMITS['model_requests'],cap);self.assertEqual(len(p.base.CASES),1)
        with self.assertRaises(SystemExit):p.main(['--case','all'])
        self.assertEqual(p.main(['--case','body-danger','--execute']),2)
        p.verify()
    async def test_danger_has_no_provider_calls_and_help_not_played(self):
        for name in ('body-danger','death-danger'):
            model=old.Model(old.plan());r=await p.run(UnifiedProviders(old.Speech(),model),name);p.validate(r,name)
            a,b=r['cases'][0]['turns'];self.assertTrue(a['reply_final_segment_ack'])
            self.assertEqual(b['model_attempts'],[]);self.assertEqual(b['tts_requests'],0)
            self.assertEqual(b['status'],'local_help_protocol_only');self.assertFalse(b['final_ack'])
            self.assertTrue(b['local_help']);self.assertTrue(r['cleanup_confirmed'])
    async def test_first_failure_never_runs_next_input(self):
        model=old.Model(old.plan());model.allowed=False
        r=await p.run(UnifiedProviders(old.Speech(),model),'shared-intent')
        self.assertTrue(r['stopped']);self.assertEqual(len(r['cases'][0]['turns']),1)
        self.assertFalse(r['cases'][0]['turns'][0]['actual_complete_ack_texts'])
        with self.assertRaises(ValueError):p.validate(r,'shared-intent')
    async def test_cold_actual_session_plan_review_ack(self):
        model=old.Model(old.plan());model.next_plan['sentences']=['这是合成第一句。','这是合成第二句。'];r=await p.run(UnifiedProviders(old.Speech(),model),'cold-query');p.validate(r,'cold-query')
        e=r['cold_seed'];self.assertEqual(e['archive_sources'],65);self.assertTrue(e['not_hot']);self.assertTrue(e['not_recent'])
        self.assertEqual(e['before_heard'],70);self.assertEqual(e['after_heard'],8)
        turn=r['cases'][0]['turns'][0];self.assertTrue(turn['reply_final_segment_ack'])
        reviews=[x for x in r['trace'] if x['kind']=='review'];self.assertEqual([x['phase'] for x in reviews],['whole','segment','segment'])
        self.assertTrue(all(x['allow'] and x['quality'] for x in reviews))
        bad=copy.deepcopy(r);bad['cold_seed']['session_binding_digest']='different'
        with self.assertRaises(ValueError):p.validate(bad,'cold-query')
        bad=copy.deepcopy(r)
        for row in bad['trace']:
            if row['kind']=='plan':row['context']['facts']={}
        with self.assertRaises(ValueError):p.validate(bad,'cold-query')
        bad=copy.deepcopy(r)
        for row in bad['trace']:
            if row['kind']=='review':row['context']['facts']={}
        with self.assertRaisesRegex(ValueError,'cold_review_basis'):p.validate(bad,'cold-query')
    async def test_shared_repair_preserved_extra_plan_denied(self):
        from tests.v2.test_plan_repair import RepairModel
        # The reviewed base and real production retry path, not a harness loop.
        p.select('shared-intent');model=RepairModel()
        p.base.TURNS['shared-intent']=('我们每人一句，继续编故事。',)
        r=await p.base.run_group(UnifiedProviders(old.Speech(),model))
        self.assertFalse(r['stopped']);self.assertEqual(model.plan_calls,2);self.assertEqual(model.fact_calls,1)
        p.select('shared-intent');guard=p.base.Guard();meter=p.base.Meter(old.Model(old.plan()),guard)
        for _ in range(2):await meter.complete('synthetic',{},schema={'properties':{'mode':{}}})
        with self.assertRaises(RuntimeError):await meter.complete('synthetic',{},schema={'properties':{'mode':{}}})
        self.assertEqual(len(guard.model),2);self.assertEqual(guard.denials[-1]['reason'],'declared_read_stage_cap')

    async def test_facts_before_plan_uses_own_fixed_input_not_last_plan(self):
        model=old.Model(old.plan());trace=p.Trace(model,'shared-intent')
        for number,text in enumerate(p.CASES['shared-intent'],1):
            await trace.complete('提取孩子',{'text':text},schema={'properties':{'facts':{}}})
            self.assertEqual(trace.rows[-1]['turn'],number)
            await trace.complete('PLAN',{'text':text,'context':{}},schema={'properties':{'mode':{}}})
        self.assertEqual([(r['kind'],r['turn']) for r in trace.rows],[('facts',1),('plan',1),('facts',2),('plan',2)])
        self.assertEqual(len(model.requests),4)
        with self.assertRaises(ValueError):await trace.complete('提取孩子',{'text':'OUT_OF_SCOPE_CANARY'},schema={'properties':{'facts':{}}})
        self.assertEqual(len(model.requests),4);self.assertNotIn('OUT_OF_SCOPE_CANARY',str(trace.rows))
