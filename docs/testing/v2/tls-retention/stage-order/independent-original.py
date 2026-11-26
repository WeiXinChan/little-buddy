import sys,pathlib,json,copy,tempfile,unittest,hashlib
root=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(root/'source'))
from scripts import v2_tls_retention as m
from tests.v2.test_tls_retention_preparation import semantic_fixture
class Boundaries(unittest.TestCase):
    def validate(self,change):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'report';nonce='a'*32
            c=semantic_fixture(['--arm','retain_plain','--nonce',nonce,'--artifact',str(p)])
            child=json.loads(c.stdout);r=json.loads(p.read_bytes());change(r)
            p.write_text(json.dumps(r));raw=p.read_bytes();child.update(full_report_bytes=len(raw),full_report_sha256=hashlib.sha256(raw).hexdigest())
            m.validate_child(child,'retain_plain',nonce,p)
    def test_reversed_fault_stage_sequence_must_reject(self):
        def reverse(r):
            rows=r['resource_samples'];a=next(x for x in rows if x['phase']=='before_network_fault');b=next(x for x in rows if x['phase']=='after_network_fault')
            a['phase'],b['phase']=b['phase'],a['phase']
        with self.assertRaises(m.Rejected):self.validate(reverse)
    def test_single_required_field_missing_rejects(self):
        for key in ('backend_fds','elapsed','phase','active_operations'):
            with self.subTest(key=key),self.assertRaises(m.Rejected):self.validate(lambda r:r['resource_samples'][0].pop(key))
    def test_diagnostic_arbitrary_values_never_survive_allowlist(self):
        raw=b'{"phase":"report_saved","cleanup":"unknown","secret":"SYNTHETIC"}\n{"phase":"SYNTHETIC","cleanup":"SYNTHETIC"}'
        self.assertEqual(m.safe_diagnostics(raw)['records'],[dict(phase='report_saved',cleanup='unknown')])
if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Boundaries));sys.exit(not result.wasSuccessful())
