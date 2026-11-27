import unittest,json,tempfile
from pathlib import Path
from scripts import v2_semantic_recheck as r
from tests.v2 import test_m05 as old
from backend.v2.companion import UnifiedProviders

class Offline(unittest.IsolatedAsyncioTestCase):
    async def test_actual_pipeline_retains_outputs_and_same_role_session(self):
        model=old.Model(old.plan())
        result=await r.run_group(UnifiedProviders(old.Speech(),model))
        r.validate_result(result)
        self.assertEqual([len(c['turns']) for c in result['cases']],[1,2])
        self.assertNotEqual(result['cases'][0]['session_binding_digest'],result['cases'][1]['session_binding_digest'])
        self.assertIsNone(result['semantic_pass'])
        self.assertTrue(result['cases'][1]['turns'][0]['actual_complete_ack_texts'])
        self.assertTrue(result['cleanup_confirmed'])
    async def test_second_plan_is_denied_before_provider_call(self):
        m=old.Model(old.plan());g=r.Guard();meter=r.Meter(m,g)
        schema={'properties':{'mode':{}}}
        await meter.complete('synthetic',{},schema=schema)
        with self.assertRaises(RuntimeError):await meter.complete('synthetic',{},schema=schema)
        self.assertEqual(len(m.requests),1)
    async def test_failure_closes_group_and_records_only_fixed_kind(self):
        class Fail:
            model=r.MODEL
            async def complete(self,*a,**kw):raise ValueError('SECRET_CANARY')
        g=r.Guard();m=r.Meter(Fail(),g)
        with self.assertRaises(ValueError):await m.complete('synthetic',{},schema={})
        self.assertFalse(g.open)
        with self.assertRaises(RuntimeError):await m.complete('synthetic',{},schema={})
        self.assertEqual(len(g.model),1);self.assertNotIn('SECRET_CANARY',str(g.model))
    async def test_facts_mismatch_keeps_diagnostics_help_and_zero_synthesis(self):
        m=old.Model(old.plan());m.extracted=[{'key':'rule','value':'FORGED_CANARY'}]
        result=await r.run_group(UnifiedProviders(old.Speech(),m))
        first=result['cases'][0]['turns'][0]
        self.assertEqual(first['error']['contract'],'fact_source_mismatch')
        self.assertTrue(first['local_help']);self.assertEqual(first['tts_requests'],0)
        self.assertEqual(first['actual_complete_ack_texts'],[])
    async def test_disabled_does_not_verify_source_or_open_config(self):
        from unittest.mock import patch
        with patch.object(r,'verify_source',side_effect=AssertionError('must not read')):
            self.assertEqual(r.main([]),0)
            self.assertEqual(r.main(['--execute']),2)
    async def test_pin_matches_requested_production_source(self):
        self.assertEqual(len(r.verify_source()),64)
