import asyncio,json,tempfile,ssl,subprocess,unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import asynccontextmanager
from scripts import v2_stage_probe as p
from backend.v2.companion import UnifiedProviders
from backend.v2 import timing
from tests.v2.test_m05 import Model,Speech,plan

class Probe(unittest.IsolatedAsyncioTestCase):
    def test_disabled_never_loads_fixture_or_credentials(self):
        with patch.object(p,'fixture',side_effect=AssertionError()),patch.object(p,'worker',side_effect=AssertionError()):self.assertEqual(p.main([]),0)
    def test_global_and_stage_caps_before_provider(self):
        meter=p.Allowance()
        for stage in ['endpoint','endpoint','plan','plan','facts','facts','review','review','review']:meter.take('text',stage)
        with self.assertRaises(p.GateError):meter.take('text','review')
        self.assertEqual(meter.calls['text'],9)
        m=p.Allowance()
        with self.assertRaises(p.GateError):m.take('text','compact')
        self.assertEqual(m.calls['text'],0)
        for kind,cap in [('asr',1),('tts',4)]:
            m=p.Allowance()
            for _ in range(cap):m.take(kind)
            with self.assertRaises(p.GateError):m.take(kind)
            self.assertEqual(m.calls[kind],cap)
    async def test_supplier_failure_closes_gate_and_no_harness_retry(self):
        class Inner:
            calls=0
            async def complete(self,*a,**k):self.calls+=1;raise RuntimeError('PRIVATE_BODY')
        inner=Inner();meter=p.Allowance();model=p.MeterModel(inner,meter)
        with self.assertRaises(RuntimeError):await model.complete('',{},schema={'properties':{'mode':{}}})
        with self.assertRaises(p.GateError):await model.complete('',{},schema={'properties':{'mode':{}}})
        self.assertEqual(inner.calls,1)
    async def test_images_all_refused_before_io(self):
        providers=UnifiedProviders(Speech(),Model(plan()));meter=p.Allowance();p.forbid_images(providers,meter)
        for name in ('prepare_visual','prepare_generated_image','prepare_dynamic_visual'):
            with self.assertRaises(p.GateError):await getattr(providers,name)('synthetic')
        self.assertEqual(meter.calls,dict(asr=0,text=0,tts=0));self.assertIsNone(providers.dynamic_images)
    async def test_asr_mismatch_is_boolean_only_and_rejected(self):
        class S:
            @asynccontextmanager
            async def recognize(self,rate):
                class Rec:
                    async def finish(self):return 'PRIVATE_OTHER_INPUT'
                yield Rec()
        meter=p.Allowance();speech=p.MeterSpeech(S(),meter)
        with self.assertRaises(p.GateError):
            async with speech.recognize(16000) as rec:await rec.finish()
        self.assertFalse(speech.empty);self.assertFalse(speech.conforms);self.assertTrue(meter.stopped)
    async def test_complete_real_loopback_tls_path_and_cleanup_with_synthetic_providers(self):
        class S(Speech):
            @asynccontextmanager
            async def recognize(self,rate):
                class Rec:
                    async def write(self,pcm):pass
                    async def finish(self):return '你好，请用一句话介绍你自己。'
                yield Rec()
        meter=p.Allowance();speech=p.MeterSpeech(S(),meter)
        providers=UnifiedProviders(speech,p.MeterModel(Model(plan()),meter));p.forbid_images(providers,meter)
        with tempfile.TemporaryDirectory() as tmp:
            t=Path(tmp)
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost','-keyout',str(t/'key'),'-out',str(t/'cert')],check=True,timeout=5,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(t/'cert',t/'key');client=ssl.create_default_context(cafile=str(t/'cert'))
            trace=timing.Trace()
            async with asyncio.timeout(8):r=await p.exercise(providers,meter,b'\0\0'*320,tls,client,'A'*40,trace)
        self.assertEqual(r['terminal'],'reply_complete');self.assertTrue(r['cleanup']['confirmed']);self.assertTrue(speech.conforms)
        self.assertEqual(meter.calls,dict(asr=1,text=4,tts=1))
        stages=[e['stage'] for e in trace.rows]
        self.assertIn('effective_ack',stages);self.assertIn('asr_final',stages);self.assertIn('asr_released',stages)
        self.assertFalse(trace.truncated)
