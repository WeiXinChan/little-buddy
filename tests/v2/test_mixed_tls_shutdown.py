"""Light shutdown-only witnesses; original counterexample inputs remain frozen."""
import copy,json,unittest
from pathlib import Path
from scripts import v2_mixed_tls as m
from tests.v2 import test_mixed_tls_preparation as fixtures

class Shutdown(unittest.TestCase):
    def test_original_two_mutations_reject_without_changing_frozen_inputs(self):
        root=Path(__file__).resolve().parents[2]/'docs/testing/v2/mixed-tls/shutdown-fix'
        plan=m.Plan(duration=90)
        for item in json.loads((root/'original-inputs.json').read_bytes()):
            with self.subTest(mutation=item['mutation']),self.assertRaises(m.p.Rejected):m.validate_report(item['report'],plan)
    def test_complete_normal_shutdown_positive_and_each_field_negative(self):
        plan,r=fixtures.fixture();m.validate_report(r,plan)
        bad={'active':True,'quarantined':True,'finished':False,'generation':True,'same_session':True,'recognition_active':True,
             'pending':1,'retired':1,'errors':1,'heard':1,'pending_audio':1,'played_count':1,'capture_bytes':640,'asr_active':1,'tts_active':1,
             'binding':'a'*64,'played_anchor':'a'*64,'state_hash':'a'*64,'game':'story','rules_hash':'a'*64,'roles_hash':'a'*64,
             'constructed':3,'process':dict(pid=21,start_ticks=100)}
        for key,value in bad.items():
            with self.subTest(key=key):
                report=copy.deepcopy(r);report['shutdown'][key]=value
                with self.assertRaises(m.p.Rejected):m.validate_report(report,plan)
    def test_missing_unknown_and_bool_as_zero_are_not_closed(self):
        plan,r=fixtures.fixture()
        for key in r['shutdown']:
            with self.subTest(missing=key):
                report=copy.deepcopy(r);report['shutdown'].pop(key)
                with self.assertRaises(m.p.Rejected):m.validate_report(report,plan)
        for key in ('pending','retired','errors','heard','pending_audio','played_count','constructed'):
            for value in (False,None,'0'):
                with self.subTest(key=key,value=value):
                    report=copy.deepcopy(r);report['shutdown'][key]=value
                    with self.assertRaises(m.p.Rejected):m.validate_report(report,plan)
    def test_constructed_must_match_each_real_release_not_just_attempt_count(self):
        plan,r=fixtures.fixture()
        for change in (lambda r:r['connections'][0]['release'].update(constructed=2),
                       lambda r:r['connections'][1]['release'].update(constructed=1),
                       lambda r:r['connections'][1]['release'].update(finished=False),
                       lambda r:r['connections'][1]['release'].update(binding='a'*64),
                       lambda r:r['shutdown'].update(constructed=1)):
            report=copy.deepcopy(r);change(report)
            with self.assertRaises(m.p.Rejected):m.validate_report(report,plan)

class ProducerSemantics(unittest.IsolatedAsyncioTestCase):
    async def test_real_service_state_without_current_peer_has_normal_shutdown_shape(self):
        # No service/socket/worker created. Use the actual state producer's default
        # no-peer semantics, not a dictionary of mechanically expected flags.
        service=m.MixedService(m.Plan(duration=90));state=service.state()
        m.validate_shutdown(state,[],state['process'])
        self.assertEqual(state['constructed'],0);self.assertFalse(state['active']);self.assertIsNone(service.peer)
