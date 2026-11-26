"""Preparation tests only: no real soak, tracemalloc.start, subprocess, or lock."""
import gc
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from scripts import v2_soak_memory as m

class Diagnostic(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def report(self):
        return dict(layer='synthetic_text_real_voicepeer_json_duplex_simulated_ack',cloud_enabled=False,device_executed=False,
                    attempts=[dict(index=0,status='delivered'),dict(index=1,status='interrupted')],
                    sampling=dict(observations=3),resource_samples=[dict(elapsed=0,backend_rss_bytes=100),
                    dict(elapsed=600,backend_rss_bytes=110),dict(elapsed=3600.002,backend_rss_bytes=120)])
    def test_read_only_analyzer_preserves_all_rows_and_is_not_heap_attribution(self):
        p=self.root/'report';raw=json.dumps(self.report()).encode();p.write_bytes(raw)
        with patch.object(m,'heavy_lock',side_effect=AssertionError('no lock')),patch.object(m.subprocess,'run',side_effect=AssertionError('no execution')):
            r=m.analyze(p)
        self.assertEqual(p.read_bytes(),raw);self.assertEqual(r['attempts'],2);self.assertEqual(r['sample_rows'],3)
        self.assertEqual(r['rss_delta'],20);self.assertEqual(r['bands'][-1]['samples'],1)
        self.assertEqual(r['source_expected_owner_task_handles'],5);self.assertFalse(r['production_leak_confirmed'])
        self.assertEqual(r['attribution'],'unknown');self.assertFalse(r['profile_executed'])
    def test_unknown_cloud_or_device_report_is_rejected(self):
        for changes in (dict(cloud_enabled=True),dict(device_executed=True),dict(sampling=dict(observations='PRIVATE'))):
            p=self.root/'report';p.write_text(json.dumps(dict(self.report(),**changes)))
            with self.assertRaises(m.Invalid):m.analyze(p)
    def test_no_body_paths_or_traceback_source_are_in_analyzer_output(self):
        p=self.root/'report';r=self.report();r['PRIVATE']='CHILD_BODY';p.write_text(json.dumps(r))
        out=json.dumps(m.analyze(p));self.assertNotIn('CHILD_BODY',out);self.assertNotIn(str(self.root),out)
    def test_weak_observer_cannot_keep_cycle_alive(self):
        class Item:pass
        registry=m.WeakRegistry();obj=Item();obj.self=obj;registry.remember('peer',obj)
        self.assertEqual(registry.counts()['peer']['live'],1)
        del obj;gc.collect()
        self.assertEqual(registry.counts()['peer']['live'],0)
    def test_shared_report_estimate_counts_shared_reference_once_and_bounds_work(self):
        x=[1,2,3];shared={'a':x,'b':x};copies={'a':[1,2,3],'b':[1,2,3]}
        self.assertLess(m.deep_size(shared),m.deep_size(copies))
        with self.assertRaises(m.Invalid):m.deep_size(copies,limit=1)
    def test_allocation_groups_are_allocation_sites_never_local_values_or_paths(self):
        class Snapshot:
            def statistics(self,kind):
                self.kind=kind
                return [SimpleNamespace(traceback=[SimpleNamespace(filename='/PRIVATE/backend/v2/voice.py')],size=30,count=2),
                        SimpleNamespace(traceback=[SimpleNamespace(filename='/PRIVATE/scripts/v2_soak_memory.py')],size=10,count=1)]
        r=m.allocation_groups(Snapshot())
        self.assertEqual(r['production_voice']['bytes'],30);self.assertEqual(r['measurement']['bytes'],10)
        self.assertNotIn('PRIVATE',json.dumps(r))
    def test_default_profile_and_hidden_worker_cannot_execute_or_take_lock(self):
        for args in (['profile','--output',str(self.root/'out')],['_worker','--arm','traced','--attempts','6','--artifact',str(self.root/'artifact')]):
            with patch.object(m,'profile',side_effect=AssertionError('must not run')),patch.object(m,'worker',side_effect=AssertionError('must not run')),patch.object(m,'heavy_lock',side_effect=AssertionError('no lock')),redirect_stdout(io.StringIO()):
                self.assertEqual(m.cli(args),2)
        self.assertFalse((self.root/'artifact').exists())
    def test_profile_invalid_bounds_fail_before_lock_and_worker_needs_real_fd(self):
        with patch.object(m,'heavy_lock',side_effect=AssertionError('no lock')):
            for n,t in ((120,30),(6,1000)):
                with self.assertRaises(m.Invalid):m.profile(self.root/'out',n,t)
        with self.assertRaises(m.Invalid):m.check_worker_lock(-1)

    def test_failed_worker_metadata_is_final_and_no_second_arm_runs(self):
        # Only parent bookkeeping with fake archive/process/lock; no worker,
        # tracer, frozen production import, or actual lock is executed.
        import tarfile
        from contextlib import contextmanager
        @contextmanager
        def lock():yield 42
        buffer=io.BytesIO()
        with tarfile.open(fileobj=buffer,mode='w'):pass
        from tests.v2.test_soak_memory_worker_validation import worker_fixture
        def callback(args,**kwargs):
            result=worker_fixture(args,cleanup_confirmed=False)
            return type('Fake',(),{'stdout':json.dumps(result).encode()})()
        out=self.root/'out'
        with patch.object(m,'heavy_lock',lock),patch.object(m.subprocess,'check_output',return_value=buffer.getvalue()),patch.object(m.subprocess,'run',side_effect=callback) as command:
            with self.assertRaises(m.Invalid):m.profile(out,6,30)
        self.assertEqual(command.call_count,1)
        self.assertEqual(json.loads((out/'result.json').read_text())['status'],'workload_or_cleanup_failed_stopped')
