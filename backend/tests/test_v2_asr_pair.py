"""Pure offline: fake clock/socket and synthetic PCM. No credentials."""
import importlib.util,json,tempfile,unittest
from pathlib import Path
from contextlib import asynccontextmanager
from unittest.mock import patch
SCRIPT=Path(__file__).resolve().parents[2]/'scripts/v2_asr_pair.py'
spec=importlib.util.spec_from_file_location('asr_pair',SCRIPT);p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
PCM=bytes(i%251 for i in range(p.SAMPLES*2))
class Clock:
    def __init__(self):self.t=10.
    def now(self):return self.t
    async def until(self,t):self.t=max(self.t,t)
class FakeSpeech:
    def __init__(self,clock,row,stamp,delay,fail=False,text=p.REFERENCE):
        self.clock=clock;self.row=row;self.stamp=stamp;self.delay=delay;self.fail=fail;self.text=text;self.events=[]
        self.reader=None;self.release_failed=False;self.last_release=None;self.release_tasks=set()
    @asynccontextmanager
    async def recognize(self,rate):
        self.origin=self.clock.now();self.row['socket_attempts']+=1;self.row['starts']+=1
        await self.clock.until(self.origin+self.delay);self.stamp('ready')
        try:
            if self.fail:raise RuntimeError('sensitive_provider_body')
            yield self
        finally:self.last_release={'confirmed':True}
    async def write(self,b):self.events.append((self.clock.now(),b))
    async def finish(self):
        self.row['finishes']+=1;self.row['task_finished']=True;self.stamp('finish')
        await self.clock.until(self.clock.now()+.15);return self.text
class PairTest(unittest.IsolatedAsyncioTestCase):
    async def run_case(self,delay=0,fail=False,text=p.REFERENCE):
        clock=Clock();made=[];report={'trials':[]}
        def factory(row,stamp):
            s=FakeSpeech(clock,row,stamp,delay,fail,text);made.append(s);return s
        code=await p.pair(PCM,report,factory,lambda:None,clock)
        return code,report,made
    async def test_pair_bytes_counts_finish_reference(self):
        code,r,made=await self.run_case(.65)
        self.assertEqual(code,0);self.assertEqual(len(made),2)
        for s in made:
            self.assertEqual(b''.join(b for _,b in s.events),PCM)
            self.assertEqual((s.row['starts'],s.row['finishes'],s.row['readtaskpending']),(1,1,0))
            self.assertEqual(s.row['actualpcm_sha256'],p.digest(PCM))
            self.assertGreaterEqual(s.row['timing_ms']['finish'],300-1e-6)
        self.assertEqual(r['comparison'],dict(equal=True,normalizedeq=True))
    async def test_no_future_bytes_late_ready_catchup_original_origin(self):
        _,_,made=await self.run_case(.65);s=made[1];offset=0
        for t,b in s.events:
            offset+=len(b);self.assertGreaterEqual(t+1e-9,s.origin+offset/(2*p.RATE))
        self.assertEqual([t for t,_ in s.events[:3]],[s.origin+.65]*3)
        self.assertAlmostEqual(s.events[3][0],s.origin+.8)
        self.assertAlmostEqual(s.events[-1][0],s.origin+p.SAMPLES/p.RATE)
    async def test_ready_after_expression_never_reanchors(self):
        _,_,made=await self.run_case(4);s=made[1]
        self.assertEqual(len({t for t,_ in s.events}),1)
        self.assertAlmostEqual(s.row['timing_ms']['finish'],(4-p.SAMPLES/p.RATE)*1000,delta=.001)
    async def test_old_waits_expression_and_quiet(self):
        _,_,made=await self.run_case();self.assertAlmostEqual(made[0].row['timing_ms']['open'],300)
        self.assertLess(made[1].row['timing_ms']['open'],0)
    async def test_old_failure_no_new_retry_or_body(self):
        code,r,made=await self.run_case(fail=True)
        self.assertEqual(code,1);self.assertEqual(len(made),1);self.assertEqual(r['trials'][0]['finishes'],0)
        self.assertNotIn('sensitive',json.dumps(r))
    async def test_old_reference_mismatch_stops_new(self):
        code,r,made=await self.run_case(text='fixture mismatch')
        self.assertEqual(code,1);self.assertEqual(len(made),1);self.assertNotIn('fixture mismatch',json.dumps(r))
    async def test_unconfirmed_cleanup_no_new(self):
        clock=Clock();made=[];r={'trials':[]}
        def factory(row,stamp):
            s=FakeSpeech(clock,row,stamp,0);s.release_failed=True;made.append(s);return s
        self.assertEqual(await p.pair(PCM,r,factory,lambda:None,clock),1);self.assertEqual(len(made),1)
    async def test_command_caps_disk_before_io(self):
        events=[];row=p.new_row('old')
        class Socket:
            async def send(self,value):events.append(('send',value))
        task=p.MeasuredTask(Socket(),row,lambda:events.append(('disk',row['starts'],row['finishes'])),lambda n:events.append(('stamp',n)))
        await task.command('run-task');await task.command('finish-task')
        self.assertEqual(events[0],('disk',1,0));self.assertEqual(events[2],('disk',1,1))
        for action in ('run-task','finish-task','continue-task'):
            with self.assertRaises(p.GuardError):await task.command(action)
    async def test_cancel_releases_reader_stops_pair(self):
        import asyncio
        clock=Clock();made=[];r={'trials':[]};entered=asyncio.Event()
        class Blocking(FakeSpeech):
            async def finish(self):
                self.row['finishes']+=1;self.stamp('finish');entered.set()
                await asyncio.Future()
        def factory(row,stamp):
            s=Blocking(clock,row,stamp,0);made.append(s);return s
        task=asyncio.create_task(p.pair(PCM,r,factory,lambda:None,clock))
        await entered.wait();task.cancel();self.assertEqual(await task,1)
        self.assertEqual(len(made),1);self.assertTrue(r['trials'][0]['cleanup_confirmed'])
    async def test_usage_validation_cumulative_no_strings(self):
        row=p.new_row('old');task=p.MeasuredTask(None,row,lambda:None,lambda n:None)
        def event(v,kind='result-generated',ident=None):return json.dumps({'header':{'task_id':task.id if ident is None else ident,'event':kind},'payload':{'usage':{'duration':v,'secret':'body'}}})
        task.event(event(3));task.event(event(2));task.event(event(3,'task-finished'))
        self.assertEqual(row['usage_max'],{'duration':3});self.assertEqual(row['usage_final'],{'duration':3})
        with self.assertRaises(Exception):task.event(event(99,ident='wrong'))
        self.assertNotIn('secret',json.dumps(row));self.assertEqual(row['usage_max']['duration'],3)
class GuardTest(unittest.TestCase):
    def test_disabled(self):
        with patch.object(p,'load_config',side_effect=AssertionError),patch.object(p,'source_guard',side_effect=AssertionError):self.assertEqual(p.main([]),0)
    def test_ledger_cap_and_disk(self):
        rows=[];ledger=p.Ledger(lambda:rows.append(ledger.calls));ledger.reserve({});ledger.reserve({})
        self.assertEqual(rows,[1,2])
        with self.assertRaises(p.GuardError):ledger.reserve({})
        ledger=p.Ledger(lambda:None);ledger.stopped=True
        with self.assertRaises(p.GuardError):ledger.reserve({})
    def test_private_output_exclusive(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'run';p.private_output(out);p.save(out/'result.json',{'calls':0})
            self.assertEqual(out.stat().st_mode&0o777,0o700);self.assertEqual((out/'result.json').stat().st_mode&0o777,0o600)
            with self.assertRaises(p.GuardError):p.private_output(out)
    def test_wrong_fixture_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'x';f.write_bytes(b'not allowed')
            with patch.object(p,'FIXTURE',f),self.assertRaises(p.GuardError):p.fixture()
    def test_dirty_tool_rejected(self):
        with self.assertRaises(p.GuardError):p.source_guard(p.SOURCE)
if __name__=='__main__':unittest.main()
