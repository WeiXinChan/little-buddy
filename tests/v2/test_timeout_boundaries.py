"""Production VoicePeer.run, real JSON protocol, local providers, controlled clock."""
import asyncio,base64,unittest
from contextlib import asynccontextmanager
from backend.v2.voice import VoicePeer
from backend.v2.failure_observer import FailureWindow,timeout
from tests.v2 import test_post_solo_probe as protocol

class TimeoutProtocol(unittest.IsolatedAsyncioTestCase):
    peer_type=VoicePeer
    for name in ('asyncSetUp','asyncTearDown','start_runner','send','until','finish_reply','heartbeat_processed','probe'):
        locals()[name]=getattr(protocol.FullProtocol,name)
    def observe(self):
        self.rows=[];self.window=FailureWindow(self.rows.append,clock=self.clock);self.window.attach(self.peer)
    async def beat(self,t):
        self.clock.now=t;await self.send('heartbeat');await self.heartbeat_processed(t+15)
    async def failure(self):
        e=await self.until('failure');self.assertEqual(e['code'],'timeout');await self.run
        self.assertTrue(self.peer.closed)
    async def test_healthy_silence_and_quiet_pcm(self):
        self.observe();await self.send('wake')
        for t in range(105,151,5):
            await self.beat(t)
            await self.send('input',pcm=base64.b64encode(b'\0\0'*320).decode(),speech=False,age_ms=0)
            await asyncio.sleep(.11);self.assertFalse(self.run.done());self.assertFalse(self.peer.awaiting_input)
        self.assertFalse(self.rows)
    async def test_heartbeat_is_last_received_plus_15(self):
        self.observe();await self.beat(110);await self.send('wake')
        self.clock.now=124.999;await asyncio.sleep(.11);self.assertFalse(self.run.done())
        self.clock.now=125;await self.failure()
        self.assertEqual(self.rows[-1]['source'],'session_monitor')
        self.assertEqual(self.rows[-1]['expiry'],'heartbeat_timeout')
        self.assertEqual(self.rows[-1]['heartbeat_remaining_ms'],0)
    async def test_input_without_probe(self):
        self.observe();self.clock.now=105;await self.send('advance',revision=1)
        await self.send('input',pcm='AQA=',speech=True,age_ms=0)
        async with asyncio.timeout(1):
            while not self.peer.awaiting_input:await asyncio.sleep(0)
        await self.beat(110);await self.beat(119);self.assertEqual(self.peer.input_budget.deadline,120)
        self.clock.now=120;await self.failure()
        self.assertEqual(self.rows[-1]['source'],'input_monitor')
        self.assertEqual(self.rows[-1]['input_remaining_ms'],0)
        self.assertGreater(self.rows[-1]['heartbeat_remaining_ms'],0)
    async def test_stalled_endpoint(self):
        self.observe();self.model.block=True
        await self.probe(1,110);await asyncio.wait_for(self.model.entered.get(),1)
        await self.beat(120);self.clock.now=125;await self.failure()
        self.assertEqual(self.rows[-1]['source'],'input_monitor')
        self.assertEqual(self.rows[-1]['input_remaining_ms'],0)
    async def test_thinking_does_not_pause_heartbeat(self):
        self.observe();self.model.completion='thinking';self.model.semantic_unknown=True
        await self.probe(1,110);e=await self.until('endpoint');self.assertEqual(e['completion'],'thinking')
        for t in range(115,176,5):
            await self.beat(t);await asyncio.sleep(.11);self.assertFalse(self.run.done())
        self.clock.now=190;await self.failure()
        self.assertEqual(self.rows[-1]['expiry'],'heartbeat_timeout');self.assertTrue(self.rows[-1]['thinking'])
    async def test_provider_timeout_during_input_is_not_unknown(self):
        self.observe()
        @asynccontextmanager
        async def recognize(rate):
            class ASR:
                async def write(self,pcm):pass
                async def finish(self):raise TimeoutError('PRIVATE')
            yield ASR()
        self.speech.recognize=recognize
        await self.probe(1,110)
        e=await self.until('failure');self.assertEqual(e['code'],'timeout')
        self.assertEqual(self.rows[-1]['source'],'input_analysis')
        self.assertGreater(self.rows[-1]['input_remaining_ms'],0)
        self.assertFalse(any(e['type']=='decision' and e.get('meaning')=='unknown' for e in self.wire.events))
    async def test_output_without_bind(self):
        self.observe();await self.probe(1,110);await self.until('endpoint')
        await self.send('seal',revision=1);e=await self.until('decision')
        self.epoch+=1;self.seq=0;await self.send('stop',intent=e['intent']);await self.until('open')
        await self.beat(120);self.clock.now=125;await self.failure()
        self.assertEqual(self.rows[-1]['source'],'session_monitor')
        self.assertTrue(self.rows[-1]['response_expired']);self.assertEqual(self.rows[-1]['output_remaining_ms'],0)

class StreamingTimeoutProtocol(TimeoutProtocol):
    @staticmethod
    def peer_type(*args,**kwargs):return VoicePeer(*args,**kwargs,stream_asr=True)

class TimeoutObserverControls(unittest.TestCase):
    def test_shared_cap_ttl_and_connection_isolation(self):
        from tests.v2.test_post_solo_probe import Wire,Clock
        from backend.v2.voice import Operation
        from backend.v2.failure_observer import record
        clock=Clock();p=VoicePeer(Wire(),object(),object(),clock=clock);rows=[]
        window=FailureWindow(rows.append,clock=clock);window.attach(p)
        record(p,Operation(p,0,0),'plan',RuntimeError('PRIVATE'))
        for _ in range(8):timeout(p,'input_monitor')
        self.assertEqual(len(rows),4);self.assertEqual(window.records,4)
        self.assertNotIn('PRIVATE',str(rows));self.assertIsNone(rows[-1]['input_remaining_ms'])
        rows.clear();clock.now=1000;timeout(p,'session_monitor');self.assertFalse(rows)
        window=FailureWindow(rows.append,clock=clock);p.failure_observer=None;window.attach(p)
        p.session.connection+=1;timeout(p,'session_monitor');self.assertFalse(rows)
    def test_null_budget_is_not_zero_and_snapshot_is_numeric_only(self):
        from tests.v2.test_post_solo_probe import Wire,Clock
        clock=Clock();p=VoicePeer(Wire(),object(),object(),clock=clock);rows=[]
        window=FailureWindow(rows.append,clock=clock);window.attach(p)
        p.input_budget.anchor=-15 # A genuine input deadline of zero, not absent.
        timeout(p,'input_monitor')
        row=rows[0];self.assertEqual(row['input_remaining_ms'],-100000)
        self.assertIsNone(row['output_remaining_ms']);self.assertIsNone(row['progress_remaining_ms'])
        self.assertEqual(set(row),{'stage','kind','source','expiry','peer','record','elapsed_ms',
            'input_remaining_ms','output_remaining_ms','progress_remaining_ms','heartbeat_remaining_ms',
            'ttl_remaining_ms','awaiting_input','thinking','response_confirmed','response_expired','active'})
    def test_disabled_and_broken_sink(self):
        from tests.v2.test_post_solo_probe import Wire,Clock
        p=VoicePeer(Wire(),object(),object(),clock=Clock());p.input_budget.speech(0)
        timeout(p,'input_monitor');self.assertFalse(hasattr(p,'failure_observer'))
        def broken(row):raise RuntimeError('PRIVATE')
        window=FailureWindow(broken);window.attach(p);timeout(p,'input_monitor')
        self.assertTrue(window.disabled);self.assertEqual(p.input_budget.deadline,115);self.assertTrue(p.session.active)
