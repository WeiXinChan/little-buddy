"""Bound, synthetic reports only: no lock, socket, workload or trace."""
from contextlib import contextmanager
from hashlib import sha256
import io,json,subprocess,tarfile,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tests.v2.test_tls_retention_preparation import semantic_fixture
from scripts import v2_tls_retention as m

class Validation(unittest.TestCase):
    def validate_mutation(self,mutate):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report';nonce='a'*32
            child=semantic_fixture(['--arm','retain_plain','--nonce',nonce,'--artifact',str(path)])
            result=json.loads(child.stdout);report=json.loads(path.read_bytes());mutate(report,result)
            raw=json.dumps(report).encode();path.write_bytes(raw)
            result.update(full_report_sha256=sha256(raw).hexdigest(),full_report_bytes=len(raw))
            return m.validate_child(result,'retain_plain',nonce,path)
    def test_individual_fault_and_recovery_evidence(self):
        for index,key,value in [(2,'rst_applied',False),(2,'rst_applied',1),(8,'pause_observed',False),(10,'pause_observed',None),
                                (3,'frames',0),(3,'acks',0),(3,'heard_before_close',0),(3,'old_ack_checked',False),
                                (3,'new_session',False),(3,'close_handshake_confirmed',False)]:
            with self.subTest(index=index,key=key):
                def mutate(r,s):
                    for rows in (r['attempts'],r['connection_ledger']):rows[index][key]=value
                with self.assertRaises(m.Rejected):self.validate_mutation(mutate)
    def test_ledger_disagreement_and_missing_fields(self):
        for key,value in [('index',2),('cleanup_confirmed',False),('pending_after_cleanup',1),('status','fault_injected')]:
            with self.subTest(key=key),self.assertRaises(m.Rejected):
                self.validate_mutation(lambda r,s:r['connection_ledger'][1].update({key:value}))
        with self.assertRaises(m.Rejected):self.validate_mutation(lambda r,s:r.pop('seed'))
    def test_legacy_counter_delta_is_preserved_and_allowed(self):
        def mutate(r,s):
            for row,account in zip(r['connection_ledger'],s['relay_accounting']):
                row['relay_network_errors']+=2;account['legacy_total']+=2;account['reset_setup_errors']['global_cleanup']+=2
        self.validate_mutation(mutate)
    def test_each_sample_dimension_and_coverage(self):
        changes=[lambda r:r['resource_samples'][0].pop('elapsed'),lambda r:r['resource_samples'][0].pop('phase'),
                 lambda r:r['resource_samples'][0].pop('backend_fds'),lambda r:r['resource_samples'][0].update(backend_threads=True),
                 lambda r:r['resource_samples'][1].update(elapsed=10),lambda r:r['resource_samples'][-1].update(phase='periodic'),
                 lambda r:r['resource_samples'][2].update(phase='periodic'),
                 lambda r:r['resource_samples'][6].update(phase='periodic'),
                 lambda r:r['resource_trends']['backend_rss_bytes'].update(maximum=999),
                 lambda r:r.update(observations=True)]
        for i,change in enumerate(changes):
            with self.subTest(i=i),self.assertRaises(m.Rejected):self.validate_mutation(lambda r,s:change(r))
    def test_supervisor_preserves_bounded_safe_evidence_on_all_failure_paths(self):
        @contextmanager
        def lock():yield 42
        archive=io.BytesIO()
        with tarfile.open(fileobj=archive,mode='w'):pass
        safe=b'{"phase":"report_saved","cleanup":"reported_confirmed","secret":"CANARY"}\nRAW_CANARY'
        for kind in ('timeout','exit','validation'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                output=Path(folder)/'out'
                def child(args,**kwargs):
                    Path(args[args.index('--artifact')+1]).write_text('full artifact')
                    if kind=='timeout':raise subprocess.TimeoutExpired(args,45,output=b'PRIVATE',stderr=safe)
                    if kind=='exit':raise subprocess.CalledProcessError(7,args,output=b'PRIVATE',stderr=safe)
                    from types import SimpleNamespace
                    return SimpleNamespace(returncode=0,stdout=b'{}',stderr=safe)
                with patch.object(m,'heavy_lock',lock),patch.object(m.subprocess,'check_output',return_value=archive.getvalue()),patch.object(m.subprocess,'run',side_effect=child) as calls:
                    with self.assertRaises(m.Rejected):m.run(output)
                self.assertEqual(calls.call_count,1)
                result=json.loads((output/'result.json').read_text());evidence=result['child_evidence']
                self.assertTrue(result['artifact_preserved']);self.assertEqual(result['status'],'failed_or_unknown_stopped')
                self.assertEqual(evidence['stderr']['records'],[dict(phase='report_saved',cleanup='reported_confirmed')])
                self.assertEqual(evidence['exit_code'],None if kind=='timeout' else 7 if kind=='exit' else 0)
                self.assertEqual(evidence['timeout'],kind=='timeout')
                for file in ('child-evidence.json','result.json'):
                    text=(output/file).read_text();self.assertNotIn('CANARY',text);self.assertNotIn('PRIVATE',text)
    def test_diagnostic_allowlist_bounds_and_malformed_values(self):
        result=m.safe_diagnostics(b'X'*70000+b'\n'+b'{"phase":[],"cleanup":{}}\n'+b'{"phase":"report_ready"}\n'*100)
        self.assertTrue(result['truncated']);self.assertLessEqual(len(result['records']),32)
        self.assertEqual(result['records'][0],dict(phase='report_ready'))
