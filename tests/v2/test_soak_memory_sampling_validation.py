"""Synthetic parent fixtures only; no profiling or actual lock/process."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from scripts import v2_soak_memory as m
from tests.v2.test_soak_memory_worker_validation import worker_fixture,fake_supervisor

class MeasurementValidation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def response(self,args,mutate=None,samples=2):
        result=worker_fixture(args,samples=samples)
        artifact=Path(args[args.index('--artifact')+1]);full=json.loads(artifact.read_bytes())
        if mutate:mutate(full)
        raw=json.dumps(full,sort_keys=True).encode();artifact.write_bytes(raw)
        result['full_report_sha256']=sha256(raw).hexdigest()
        result['report_structure'].update(file_bytes=len(raw),top_level_fields=len(full))
        return result,artifact,raw
    def rejected(self,name,mutate):
        out=self.root/name;saved=None
        def child(args,**kwargs):
            nonlocal saved
            result,artifact,saved=self.response(args,mutate)
            return SimpleNamespace(stdout=json.dumps(result).encode())
        with fake_supervisor(child) as calls:
            with self.assertRaises(m.Invalid):m.profile(out,6,30)
        result=json.loads((out/'result.json').read_text())
        self.assertEqual(calls.call_count,1);self.assertEqual(result['status'],'worker_failed_stopped')
        self.assertEqual(result['failure'],'worker_artifact_invalid');self.assertEqual(result['completed'],[])
        self.assertEqual((out/'plain-full-soak.json').read_bytes(),saved)
    def test_missing_status_and_each_sampling_field_stop_without_success_defaults(self):
        cases=[lambda f:f.pop('resource_collection_valid'),lambda f:f.pop('sampling')]
        keys=('observations','retained','evicted','errors','active_observed','continuous_peaks_known','valid','missing_metrics')
        for key in keys:cases.append(lambda f,key=key:f['sampling'].pop(key))
        for index,change in enumerate(cases):
            with self.subTest(index=index):self.rejected(str(index),change)
    def test_status_and_error_types_are_strict_and_metrics_cannot_be_missing(self):
        cases=[]
        for value in (False,1,'true',None):cases.append(lambda f,value=value:f.update(resource_collection_valid=value))
        values={'valid':(False,1,None),'errors':(1,False,0.0,'0',-1),
                'missing_metrics':(None,'',{},['backend_rss_bytes']),
                'active_observed':(False,1),'continuous_peaks_known':(True,0)}
        for key,items in values.items():
            for value in items:cases.append(lambda f,key=key,value=value:f['sampling'].update({key:value}))
        for index,change in enumerate(cases):
            with self.subTest(index=index):self.rejected(str(index),change)
    def test_counter_types_limits_and_consistency_are_checked_in_full_artifact(self):
        values={'observations':(True,2.0,-1,100001,3),'retained':(True,2.0,-1,4097,1),
                'evicted':(False,0.0,-1,100001,1)}
        index=0
        for key,items in values.items():
            for value in items:
                with self.subTest(key=key,value=value):
                    self.rejected(str(index),lambda f,key=key,value=value:f['sampling'].update({key:value}));index+=1
    def test_valid_nonidle_and_bounded_eviction_pass_without_report_rewriting(self):
        def child(args,**kwargs):
            arm=args[args.index('--arm')+1]
            result=worker_fixture(args,samples=4096)
            artifact=Path(args[args.index('--artifact')+1]);full=json.loads(artifact.read_bytes())
            if arm!='idle':
                full['sampling'].update(observations=4100,evicted=4)
                result['report_structure'].update(sample_observations=4100,sample_evicted=4)
                raw=json.dumps(full,sort_keys=True).encode();artifact.write_bytes(raw)
                result['full_report_sha256']=sha256(raw).hexdigest();result['report_structure'].update(file_bytes=len(raw))
            return SimpleNamespace(stdout=json.dumps(result).encode())
        out=self.root/'out'
        with fake_supervisor(child) as calls:r=m.profile(out,6,30)
        self.assertEqual(calls.call_count,4);self.assertTrue(r['workload_schedule_comparable'])
        for arm in ('plain','traced','traced_repeat'):
            report=json.loads((out/(arm+'-full-soak.json')).read_text())
            self.assertEqual(len(report['resource_samples']),4096)
            self.assertEqual(report['sampling']['observations'],4100);self.assertEqual(report['sampling']['evicted'],4)
        idle=json.loads((out/'idle-full-soak.json').read_text())
        self.assertNotIn('resource_collection_valid',idle);self.assertEqual(idle['sampling'],{'observations':0,'evicted':0})
        # Truthfully bind an internally consistent but above-ceiling count.
        # This must fail the new quality bound, not merely a metadata mismatch.
        def above_limit(args,**kwargs):
            result=worker_fixture(args,samples=4096)
            artifact=Path(args[args.index('--artifact')+1]);full=json.loads(artifact.read_bytes())
            full['sampling'].update(observations=100001,evicted=95905)
            raw=json.dumps(full,sort_keys=True).encode();artifact.write_bytes(raw)
            result['full_report_sha256']=sha256(raw).hexdigest()
            result['report_structure'].update(sample_observations=100001,sample_evicted=95905,file_bytes=len(raw))
            return SimpleNamespace(stdout=json.dumps(result).encode())
        invalid=self.root/'above_limit'
        with fake_supervisor(above_limit) as calls:
            with self.assertRaises(m.Invalid):m.profile(invalid,6,30)
        self.assertEqual(calls.call_count,1)
        self.assertEqual(json.loads((invalid/'result.json').read_text())['status'],'worker_failed_stopped')
    def test_idle_is_separate_and_cannot_synthesize_measurement_success(self):
        changes=[lambda f:f['sampling'].update(observations=False),lambda f:f['sampling'].update(evicted=0.0),
                 lambda f:f['sampling'].update(valid=True,errors=0,missing_metrics=[]),
                 lambda f:f.update(resource_collection_valid=True)]
        for index,change in enumerate(changes):
            out=self.root/str(index)
            def child(args,**kwargs):
                arm=args[args.index('--arm')+1]
                result,artifact,raw=self.response(args,change if arm=='idle' else None)
                return SimpleNamespace(stdout=json.dumps(result).encode())
            with fake_supervisor(child) as calls:
                with self.assertRaises(m.Invalid):m.profile(out,6,30)
            result=json.loads((out/'result.json').read_text())
            self.assertEqual(calls.call_count,4);self.assertEqual(result['status'],'worker_failed_stopped')
            self.assertEqual(result['failed_arm'],'idle');self.assertEqual(len(result['completed']),3)
            self.assertEqual(len(list(out.glob('*-full-soak.json'))),4)
    def test_exact_saved_original_bad_artifact_is_still_rejected_and_preserved(self):
        path=Path(__file__).resolve().parents[2]/'docs/testing/v2/soak-memory/mem111-03'
        original=(path/'original-full-report.json').read_bytes()
        original_metadata=json.loads((path/'original-worker-metadata.json').read_text())
        out=self.root/'out'
        def child(args,**kwargs):
            result=deepcopy(original_metadata);result['worker_id']=args[args.index('--worker-id')+1]
            Path(args[args.index('--artifact')+1]).write_bytes(original)
            return SimpleNamespace(stdout=json.dumps(result).encode())
        with fake_supervisor(child) as calls:
            with self.assertRaises(m.Invalid):m.profile(out,6,30)
        self.assertEqual(calls.call_count,1)
        self.assertEqual((out/'plain-full-soak.json').read_bytes(),original)
        self.assertEqual(json.loads((out/'result.json').read_text())['status'],'worker_failed_stopped')
