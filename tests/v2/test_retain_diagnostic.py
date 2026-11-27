from tests.v2.pin_objects import assert_git_pin,assert_rejects_changed_copy
import json,unittest
from copy import deepcopy
from unittest.mock import patch
from backend.v2.companion import UnifiedProviders
from tests.v2 import test_m05 as old
from tests.v2 import test_retain_only_probe as fixture
from scripts import v2_retain_diagnostic as diagnostic

class Model(fixture.Model):
    def __init__(self,legacy=False):super().__init__();self.review_number=0;self.legacy=legacy
    async def complete(self,instruction,data,*,schema=None):
        if '审核下一个' in instruction:
            if self.legacy:return '{"allow":false}'
            if len(self.inputs)==2:self.review_number+=1
            return json.dumps(dict(allow=True,quality=self.review_number!=3))
        raw=await super().complete(instruction,data,schema=schema)
        if '严格字段' in instruction and len(self.inputs)==2:
            value=json.loads(raw);value['sentences']=['普通合成开头。','合成质量错误的后续句。'];return json.dumps(value,ensure_ascii=False)
        return raw

class Diagnostic(unittest.IsolatedAsyncioTestCase):
    async def test_whole_segment_context_and_both_flags_preserved_without_fake_final_ack(self):
        m=Model();r=await diagnostic.run(UnifiedProviders(old.Speech(),m))
        reviews=[x for x in r['diagnostic']['trace'] if x['kind']=='review' and x['turn']==2]
        self.assertEqual([x['phase'] for x in reviews],['whole','segment','segment'])
        self.assertEqual(reviews[-1]['outcome'],'quality_denied')
        self.assertIs(reviews[-1]['allow'],True);self.assertIs(reviews[-1]['quality'],False)
        self.assertNotIn('普通合成开头。',str(reviews[0]['context']['heard']))
        self.assertIn('普通合成开头。',str(reviews[-1]['context']['heard']))
        last=r['cases'][0]['turns'][-1]
        self.assertEqual(last['actual_complete_ack_texts'],['普通合成开头。'])
        self.assertEqual(last['error']['kind'],'QualityFault');self.assertEqual(last['local_help'],[])
        self.assertFalse(last['reply_final_segment_ack']);self.assertFalse(r['diagnostic']['complete_final_ack_for_all_turns'])
        self.assertFalse(last['public_game_committed'])
    async def test_legacy_boolean_does_not_get_invented_new_cause(self):
        r=await diagnostic.run(UnifiedProviders(old.Speech(),Model(legacy=True)))
        row=next(x for x in r['diagnostic']['trace'] if x['kind']=='review')
        self.assertEqual(row['outcome'],'invalid');self.assertTrue(row['legacy_boolean_only'])
        self.assertIsNone(row['allow']);self.assertIsNone(row['quality'])
    async def test_trace_adds_no_requests_to_successful_fixed_case(self):
        base=diagnostic.base
        first=await base.run_group(UnifiedProviders(old.Speech(),fixture.Model()))
        wrapped=await diagnostic.run(UnifiedProviders(old.Speech(),fixture.Model()))
        self.assertEqual(first['totals']['model_requests'],wrapped['totals']['model_requests'])
        self.assertTrue(wrapped['diagnostic']['complete_final_ack_for_all_turns'])
    async def test_non_case_input_and_exception_messages_never_recorded(self):
        m=fixture.Model();trace=diagnostic.TraceModel(m)
        with self.assertRaises(ValueError):await trace.complete('严格字段',{'text':'arbitrary_user_input'},schema={'properties':{'mode':{}}})
        self.assertEqual(trace.records,[]);self.assertEqual(m.inputs,[])
        class Fail:
            async def complete(self,*a,**kw):raise RuntimeError('PRIVATE_EXCEPTION_CANARY')
        trace=diagnostic.TraceModel(Fail())
        with self.assertRaises(RuntimeError):await trace.complete('严格字段',{'text':diagnostic.base.TURNS['retain-only-change'][0]},schema={'properties':{'mode':{}}})
        self.assertNotIn('PRIVATE_EXCEPTION_CANARY',str(trace.records));self.assertEqual(trace.records[0]['outcome'],'upstream_failed')
    async def test_default_disabled_and_fixed_source(self):
        with patch.object(diagnostic.base,'verify_source',side_effect=AssertionError('no credentials')):
            self.assertEqual(diagnostic.main(['--case','retain-only-change']),0)
            self.assertEqual(diagnostic.main(['--case','retain-only-change','--execute']),2)
        assert_git_pin(self,diagnostic.base,'v2_retain_only_probe_pin.json')
