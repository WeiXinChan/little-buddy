import sys,pathlib,tempfile,json,copy,unittest,io,contextlib,subprocess
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).parent/'source'))
from scripts import v2_tls_retention as m
from tests.v2 import test_tls_retention_preparation as fixtures

class Independent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.examples=[];original=m.validate_child
        def capture(result,arm,nonce,artifact):
            cls.examples.append((copy.deepcopy(result),arm,nonce,pathlib.Path(artifact).read_bytes()))
            return original(result,arm,nonce,artifact)
        f=fixtures.Preparation('test_single_fourteen_parent_contract_accepts_each_explicit_arm_only_once')
        with patch.object(m,'validate_child',capture):
            r=unittest.TestResult();f.run(r)
        assert r.wasSuccessful(),r.errors+r.failures
    def seed(self):
        result,arm,nonce,raw=copy.deepcopy(self.examples[0]);return result,arm,nonce,json.loads(raw)
    def validate(self,result,arm,nonce,full):
        from hashlib import sha256
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'report';p.write_text(json.dumps(full));raw=p.read_bytes()
            result['full_report_sha256']=sha256(raw).hexdigest();result['full_report_bytes']=len(raw)
            return m.validate_child(result,arm,nonce,p)
    def test_fault_labels_without_real_rst_or_pause_evidence_must_reject(self):
        result,arm,nonce,full=self.seed()
        for row in full['attempts']+full['connection_ledger']:
            row.update(rst_applied=False,down_blocked=False,frames=0,acks=0,close_handshake_confirmed=False)
        with self.assertRaises(m.Rejected):self.validate(result,arm,nonce,full)
    def test_sampling_claim_without_any_phase_time_cleanup_metrics_must_reject(self):
        result,arm,nonce,full=self.seed()
        # Single RSS-only observation cannot prove active and post-cleanup collection.
        self.assertEqual(full['resource_samples'],[dict(backend_rss_bytes=100)])
        with self.assertRaises(m.Rejected):self.validate(result,arm,nonce,full)
    def test_ledger_contradicts_confirmed_attempt_cleanup_must_reject(self):
        result,arm,nonce,full=self.seed()
        full['connection_ledger'][3].update(cleanup_confirmed=False,pending_after_cleanup=1,session_cleared=False)
        with self.assertRaises(m.Rejected):self.validate(result,arm,nonce,full)
    def test_timeout_keeps_bounded_child_metadata_output_evidence(self):
        @contextlib.contextmanager
        def lock():yield 42
        import tarfile
        archive=io.BytesIO()
        with tarfile.open(fileobj=archive,mode='w'):pass
        def child(args,**kw):
            raise subprocess.TimeoutExpired(args,45,output=b'{"phase":"before_report","cleanup":"unknown"}',stderr=None)
        with tempfile.TemporaryDirectory() as d:
            out=pathlib.Path(d)/'out'
            with patch.object(m,'heavy_lock',lock),patch.object(m.subprocess,'check_output',return_value=archive.getvalue()),patch.object(m.subprocess,'run',side_effect=child):
                with self.assertRaises(m.Rejected):m.run(out)
            text='\n'.join(p.read_text() for p in out.iterdir())
            self.assertIn('before_report',text,'bounded child progress discarded on timeout')

if __name__=='__main__':
    r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Independent))
    sys.exit(not r.wasSuccessful())
