from tests.v2.pin_objects import assert_git_pin,assert_rejects_changed_copy
import unittest,json,tempfile
from unittest.mock import patch,AsyncMock
from scripts import v2_closeout_probe as p
from tests.v2 import test_m05 as old
from backend.v2.companion import UnifiedProviders

class Preparation(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_case_never_runs_other_groups_and_records_hidden(self):
        p.select_case('guess-object')
        model=old.Model(old.plan());model.next_plan.update(action='change',mode='guess',guess_role='setter',secrets={'answer':'SYNTHETIC_ONLY_ANSWER'},sentences=['它可以装水。'])
        result=await p.run_group(UnifiedProviders(old.Speech(),model));p.validate_result(result)
        self.assertEqual(len(result['cases']),1);self.assertEqual(len(result['cases'][0]['turns']),3)
        a,b,c=result['cases'][0]['turns']
        self.assertEqual(a['synthetic_hidden_before'],{})
        self.assertEqual(a['synthetic_hidden_after'],{'answer':'SYNTHETIC_ONLY_ANSWER'})
        self.assertEqual(a['game_after']['guess_role'],'setter')
        self.assertEqual(b['game_before']['guess_role'],'setter')
        self.assertIn('guess_normalization',a)
        self.assertEqual(b['synthetic_hidden_before'],a['synthetic_hidden_after'])
        self.assertNotIn('SYNTHETIC_ONLY_ANSWER',str(a['actual_complete_ack_texts']))
        self.assertIsNone(result['semantic_pass'])
        self.assertNotIn('G02',str([c['id'] for c in result['cases']]))
    async def test_all_four_explicit_selectors_are_single_case(self):
        for name in p.ALL_CASES:
            p.select_case(name);self.assertEqual(list(p.TURNS),[name]);self.assertEqual(len(p.CASES),1)
        with self.assertRaises(ValueError):p.select_case('all')
        with self.assertRaises(ValueError):p.select_case('G05-role-exit')
    async def test_memory_pair_has_same_latest_facts_and_actual_compact(self):
        e=p.memory_payloads();a,b=e['payloads']
        self.assertTrue(e['compact_returned']);self.assertGreater(e['after_revision'],e['before_revision'])
        self.assertGreater(e['before_heard'],e['after_heard']);self.assertEqual(a['context']['facts'],b['context']['facts'])
        self.assertIn('现在钥匙换到绿色岩石下面',str(a['context']['facts']))
        self.assertNotEqual(e['payload_hashes'][0],e['payload_hashes'][1])
        self.assertEqual(a['text'],b['text']);self.assertNotIn('expect',a)
    async def test_memory_only_two_production_plan_candidates_no_playback(self):
        model=old.Model(old.plan());providers=UnifiedProviders(old.Speech(),model)
        result=await p.memory_compare(providers);p.validate_memory(result)
        self.assertEqual(len(model.requests),2);self.assertEqual(result['tts_calls'],0)
        self.assertTrue(all(not c['played'] and not c['reviewed'] for c in result['candidates']))
        self.assertIs(providers.model,model)
    async def test_second_memory_failure_preserves_first_and_stops(self):
        class Fail(old.Model):
            async def complete(self,*a,**kw):
                if self.requests:raise ValueError('SECRET_CANARY')
                return await super().complete(*a,**kw)
        result=await p.memory_compare(UnifiedProviders(old.Speech(),Fail(old.plan())))
        self.assertTrue(result['stopped']);self.assertEqual(len(result['candidates']),1)
        self.assertEqual(result['model_requests'],2);self.assertNotIn('SECRET_CANARY',str(result))
        with self.assertRaises(ValueError):p.validate_memory(result)
    async def test_limit_refuses_third_model_and_default_never_reads_credentials(self):
        g=p.Guard();g.model_limit=2;m=p.Meter(old.Model(old.plan()),g)
        for _ in range(2):g.turn_stages={};await m.complete('synthetic',{},schema={'properties':{'mode':{}}})
        g.turn_stages={}
        with self.assertRaises(RuntimeError):await m.complete('synthetic',{},schema={'properties':{'mode':{}}})
        self.assertEqual(len(g.model),2)
        with patch.object(p,'verify_source',side_effect=AssertionError('disabled')):
            self.assertEqual(p.main(['--case','guess-object']),0)
            self.assertEqual(p.main(['--case','memory-compare','--execute']),2)
    async def test_source_pin_is_final_main(self):
        self.assertEqual(p.SOURCE,'fe49b63561a31ea5452a6693ff8be0e7c36704f4')
        assert_git_pin(self,p,'v2_closeout_probe_pin.json')

    async def test_production_sentence_repair_remains_admitted_and_metered(self):
        from tests.v2.test_plan_repair import RepairModel
        p.select_case('story-forest')
        model=RepairModel()
        # Existing production helper's first input contains explicit one-sentence rule.
        p.TURNS['story-forest']=('我们每人一句，继续编故事。',)
        result=await p.run_group(UnifiedProviders(old.Speech(),model))
        self.assertFalse(result['stopped'])
        self.assertEqual(model.plan_calls,2);self.assertEqual(model.fact_calls,1)
        turn=result['cases'][0]['turns'][0]
        self.assertEqual(turn['status'],'cloud_reply_complete_simulated_ack')
        self.assertNotIn('CANDIDATE_ONLY',str(turn['actual_complete_ack_texts']))
        self.assertEqual(result['totals']['budget_denials'],[])

    async def test_harness_third_plan_is_mechanical_denial_not_model_quality(self):
        guard=p.Guard();model=old.Model(old.plan());meter=p.Meter(model,guard)
        for _ in range(2):await meter.complete('synthetic',{},schema={'properties':{'mode':{}}})
        with self.assertRaises(RuntimeError):await meter.complete('synthetic',{},schema={'properties':{'mode':{}}})
        self.assertEqual(len(model.requests),2)
        self.assertEqual(guard.denials[-1]['reason'],'declared_read_stage_cap')
        self.assertFalse(guard.denials[-1]['network_started'])

    async def test_execution_admission_still_rejects_changed_local_source(self):
        assert_rejects_changed_copy(self,p,'v2_closeout_probe_pin.json')
