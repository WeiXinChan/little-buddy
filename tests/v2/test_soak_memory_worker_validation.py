"""Parent-only fixtures: fake lock, archive and process; never a real worker."""
from contextlib import contextmanager
from hashlib import sha256
import io
import json
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scripts import v2_soak_memory as m

def worker_fixture(args,samples=2,cleanup_confirmed=True):
    def value(key):return args[args.index(key)+1]
    arm=value('--arm');n=int(value('--attempts'));count=0 if arm=='idle' else n
    if arm=='idle':samples=0
    cleanup=dict(confirmed=cleanup_confirmed,pending_tasks=0 if cleanup_confirmed else 1,provider_reusable=None if arm=='idle' else cleanup_confirmed)
    calls=None if arm=='idle' else dict(plan=n,facts=n,safe=n)
    full=dict(attempts=[dict(index=i,scenario='fixture',injected='normal',status='delivered',observed=dict(frames=1,game_mode='chat')) for i in range(count)],
              resource_samples=[dict(phase='fixture',elapsed=i*.1) for i in range(samples)],
              sampling=dict(observations=samples,evicted=0),cleanup=cleanup,model_stage_calls=calls,cloud_enabled=False,device_executed=False)
    if arm!='idle':
        full['sampling'].update(retained=samples,errors=0,active_observed=True,continuous_peaks_known=False,valid=True,missing_metrics=[])
        full['resource_collection_valid']=True
    artifact=Path(value('--artifact'));raw=json.dumps(full,sort_keys=True).encode();artifact.write_bytes(raw)
    inputs,outputs=m.schedule_hashes(full)
    phases=[]
    for label in m.PHASES:
        traced=arm!='plain'
        phases.append(dict(phase=label,rss_bytes=100,live={},counts={},trace_current=10 if traced else None,
            trace_peak=20 if traced else None,trace_metadata_bytes=3 if traced else None,
            allocation_groups={k:dict(bytes=0,blocks=0) for k in m.GROUPS} if traced else None,
            report_reachable_bytes=1000+samples*10 if label in m.PHASES[1:3] else None))
    result=dict(format=2,worker_id=value('--worker-id'),source_sha=m.SOURCE,arm=arm,attempt_limit=n,duration_limit=max(3.,n*.3),
          attempted=count,failures=0,cleanup=cleanup,full_report_sha256=sha256(raw).hexdigest(),input_schedule_sha256=inputs,output_schedule_sha256=outputs,
          model_stage_calls=calls,reported_sample_rows=samples,
          report_structure=dict(attempt_rows=count,retained_sample_rows=samples,sample_observations=samples,sample_evicted=0,top_level_fields=len(full),file_bytes=len(raw)),
          phases=phases,context_checkpoints=[dict(index=i,sample_rows=samples,observations=samples) for i in range(count)],
          measurement_overhead=dict(phase_rows=4,context_checkpoint_rows=count,weak_registry_observations=0,weak_slots=0,tracer_frames=0 if arm=='plain' else 8),
          observer='same_weak_registry_in_plain_and_traced',attribution='unproven',rss_is_not_live_heap=True,production_modified=False)
    return result

@contextmanager
def fake_supervisor(callback):
    @contextmanager
    def lock():yield 42
    archive=io.BytesIO()
    with tarfile.open(fileobj=archive,mode='w'):pass
    with patch.object(m,'heavy_lock',lock),patch.object(m.subprocess,'check_output',return_value=archive.getvalue()),patch.object(m.subprocess,'run',side_effect=callback) as process:
        yield process

class WorkerValidation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def test_full_parent_flow_distinguishes_schedule_and_memory_controls(self):
        counts={'plain':100,'traced':200,'traced_repeat':200,'idle':0}
        def callback(args,**kwargs):
            arm=args[args.index('--arm')+1]
            return SimpleNamespace(stdout=json.dumps(worker_fixture(args,counts[arm])).encode())
        with fake_supervisor(callback) as child:r=m.profile(self.root/'out',6,30)
        self.assertEqual(child.call_count,4);self.assertTrue(r['workload_schedule_comparable'])
        self.assertFalse(r['comparable']);self.assertFalse(r['memory_controls']['comparable'])
        self.assertFalse(r['memory_controls']['retained_sample_rows_equal'])
        self.assertEqual([a['report_structure']['retained_sample_rows'] for a in r['memory_controls']['arms']],[100,200,200])
        self.assertEqual([a['measurement_overhead']['tracer_frames'] for a in r['memory_controls']['arms']],[0,8,8])
        self.assertEqual(len(list((self.root/'out').glob('*-full-soak.json'))),4)
    def test_equal_report_counts_do_not_erase_different_tracing_conditions(self):
        def callback(args,**kwargs):return SimpleNamespace(stdout=json.dumps(worker_fixture(args)).encode())
        with fake_supervisor(callback):r=m.profile(self.root/'out',6,30)
        self.assertTrue(r['workload_schedule_comparable']);self.assertTrue(r['memory_controls']['retained_sample_rows_equal'])
        self.assertFalse(r['memory_controls']['measurement_conditions_equal']);self.assertFalse(r['comparable'])
        import ast
        tree=ast.parse(Path(m.__file__).read_text())
        node=next(n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='comparable' for t in n.targets))
        incomplete=[dict(input_schedule_sha256='same',output_schedule_sha256='same',attempted=6,model_stage_calls={'plan':6},reported_sample_rows=2) for _ in range(3)]
        self.assertFalse(eval(compile(ast.Expression(node.value),'<comparison>','eval'),{'json':json},dict(actual=incomplete)))
    def test_every_missing_top_level_field_is_terminal_without_second_arm(self):
        fields=None
        def obtain(args,**kwargs):
            nonlocal fields
            result=worker_fixture(args);fields=list(result);return SimpleNamespace(stdout=json.dumps(result).encode())
        with fake_supervisor(obtain):m.profile(self.root/'template',6,30)
        for index,field in enumerate(fields):
            with self.subTest(field=field):
                out=self.root/str(index)
                def bad(args,**kwargs):
                    result=worker_fixture(args);result.pop(field);return SimpleNamespace(stdout=json.dumps(result).encode())
                with fake_supervisor(bad) as child:
                    with self.assertRaises(m.Invalid):m.profile(out,6,30)
                terminal=json.loads((out/'result.json').read_text())
                self.assertEqual(terminal['status'],'worker_failed_stopped');self.assertEqual(child.call_count,1)
                self.assertEqual(terminal['completed'],[]);self.assertTrue((out/'plain-full-soak.json').exists())
    def test_worker_identity_types_and_nested_structure_are_not_success_defaults(self):
        changes=[lambda r:r.update(source_sha='0'*40),lambda r:r.update(arm='idle'),lambda r:r.update(worker_id='old'),
                 lambda r:r.update(format=True),lambda r:r.update(attempt_limit=True),lambda r:r.update(duration_limit=float('nan')),
                 lambda r:r.update(attempted=True),lambda r:r.update(PRIVATE='CANARY'),
                 lambda r:r['cleanup'].pop('confirmed'),lambda r:r['cleanup'].update(confirmed=1),
                 lambda r:r['report_structure'].update(retained_sample_rows=200),lambda r:r['measurement_overhead'].pop('weak_slots'),
                 lambda r:r['phases'][0].update(phase='wrong'),lambda r:r['phases'][1].update(trace_current=False),
                 lambda r:r['context_checkpoints'][0].pop('observations')]
        for index,change in enumerate(changes):
            with self.subTest(index=index):
                out=self.root/str(index)
                def bad(args,**kwargs):
                    r=worker_fixture(args);change(r);return SimpleNamespace(stdout=json.dumps(r).encode())
                with fake_supervisor(bad) as child:
                    with self.assertRaises(m.Invalid):m.profile(out,6,30)
                text=(out/'result.json').read_text();r=json.loads(text)
                self.assertEqual(r['status'],'worker_failed_stopped');self.assertEqual(child.call_count,1)
                self.assertNotIn('CANARY',text);self.assertNotIn('PRIVATE',text)
    def test_invalid_second_arm_preserves_first_report_and_its_verified_result(self):
        first=None
        def callback(args,**kwargs):
            nonlocal first
            r=worker_fixture(args)
            if r['arm']=='plain':first=Path(args[args.index('--artifact')+1]).read_bytes()
            else:r={'cleanup':{},'failures':0,'attempted':6}
            return SimpleNamespace(stdout=json.dumps(r).encode())
        out=self.root/'out'
        with fake_supervisor(callback) as child:
            with self.assertRaises(m.Invalid):m.profile(out,6,30)
        r=json.loads((out/'result.json').read_text())
        self.assertEqual(child.call_count,2);self.assertEqual(r['failed_arm'],'traced')
        self.assertEqual([a['arm'] for a in r['completed']],['plain'])
        self.assertEqual((out/'plain-full-soak.json').read_bytes(),first)
        self.assertTrue((out/'traced-full-soak.json').exists())
    def test_artifact_missing_hash_changed_or_false_row_count_stops(self):
        for mode in ('missing','hash','rows'):
            with self.subTest(mode=mode):
                out=self.root/mode
                def callback(args,**kwargs):
                    r=worker_fixture(args);artifact=Path(args[args.index('--artifact')+1])
                    if mode=='missing':artifact.unlink()
                    elif mode=='hash':r['full_report_sha256']='0'*64
                    else:r['reported_sample_rows']=3;r['report_structure'].update(retained_sample_rows=3,sample_observations=3)
                    return SimpleNamespace(stdout=json.dumps(r).encode())
                with fake_supervisor(callback) as child:
                    with self.assertRaises(m.Invalid):m.profile(out,6,30)
                r=json.loads((out/'result.json').read_text())
                self.assertEqual(r['status'],'worker_failed_stopped');self.assertEqual(r['failure'],'worker_artifact_invalid')
                self.assertEqual(child.call_count,1)
    def test_comparison_failure_is_supervised_and_keeps_all_artifacts(self):
        def callback(args,**kwargs):return SimpleNamespace(stdout=json.dumps(worker_fixture(args)).encode())
        # A fixture container fails only in the comparison phase after four valid arms.
        out=self.root/'out'
        # A hash operation fails only after all four valid worker results.
        class ExplodingString(str):
            def __hash__(self):raise ValueError('PRIVATE')
        valid=m.validate_worker
        def validate(result,*args):
            valid(result,*args)
            result['input_schedule_sha256']=ExplodingString(result['input_schedule_sha256'])
        with fake_supervisor(callback) as child,patch.object(m,'validate_worker',side_effect=validate):
            with self.assertRaises(m.Invalid):m.profile(out,6,30)
        r=json.loads((out/'result.json').read_text())
        self.assertEqual(r['status'],'comparison_failed_stopped');self.assertEqual(len(r['completed']),4)
        self.assertEqual(child.call_count,4);self.assertEqual(len(list(out.glob('*-full-soak.json'))),4)
        self.assertNotIn('PRIVATE',(out/'result.json').read_text())
