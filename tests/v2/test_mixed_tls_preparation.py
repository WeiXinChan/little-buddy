"""Only metadata, small production policy/session objects and fake-clock pacing.
No real TLS, process, lock, worker or cloud; no 90/3600-second execution.
"""
import asyncio,copy,json,unittest
from dataclasses import asdict
from types import SimpleNamespace as NS
from unittest.mock import patch,AsyncMock
from scripts import v2_mixed_tls as m
from scripts import v2_persistent_tls as p

ALLOWANCE=dict(model_calls=50,tts_calls=10,tts_unicode_characters=100,reserved_units=60,account_quota_known=False,bill_cny=None)
def fixture():
    plan=m.Plan(duration=90);turns=[]
    for i in range(12):
        status='interrupted' if i==7 else 'fault_injected' if i==9 else 'duration_cutoff' if i==11 else 'delivered'
        turns.append(dict(index=i,first_audio_seconds=.01,status=status,input_seconds=6.,playback_seconds=.1 if i==7 else 0 if i in (9,11) else 2.,frames=0 if i in (9,11) else 1 if i==7 else 20,acks=0 if i in (9,11) else 1 if i==7 else 20,binding='a'*64,played_anchor='b'*64,no_partial_commit=True))
    release=dict(cleanup_confirmed=True,transport_closed=True,pending=0,retired=0,errors=0,heard=0,pending_audio=0,active=False,quarantined=False)
    rows=[dict(index=0,started=0.,completed=76.2,fault='asr_rst',status='fault_injected',turn_start=0,turn_end=10,cleanup_confirmed=True,client_cleanup=True,release=release,binding='a'*64,new_session=True,frames=161,acks=161,old_ack_checked=True,cross_connection_old_ack_checked=None,rst_applied=True),
          dict(index=1,started=76.4,completed=91.,fault='normal_close',status='duration_cutoff',turn_start=10,turn_end=12,cleanup_confirmed=True,client_cleanup=True,release=release,binding='c'*64,new_session=True)]
    samples=[]
    for t in sorted([0]+list(range(0,91,5))+[76.3,91]):
        samples.append(dict(event='before_warmup' if not samples else 'final' if t==91 else 'after_warmup' if t==76.3 else 'periodic',elapsed=t,service_process=dict(pid=20,start_ticks=100),client_process=dict(pid=10,start_ticks=90),service_resources=dict(backend_rss_bytes=100,backend_fds=7,backend_threads=1,asyncio_tasks=3),client_resources=dict(backend_rss_bytes=120,backend_fds=10,backend_threads=1,asyncio_tasks=4),allowance=ALLOWANCE))
    return plan,dict(status='duration_collected_not_acceptance',limits=asdict(plan),duration=90,collection_errors=0,cleanup_confirmed=True,forced_exit=False,service_exit=0,cloud=False,device=False,acoustic=False,acceptance=False,gc_forced=False,connections=rows,turns=turns,samples=samples,rounds=[],service_pid=20,driver_pid=10,shutdown=dict(pending=0,retired=0,errors=0,binding=None,allowance=ALLOWANCE),timing=dict(elapsed_seconds=91.,declared_input_seconds=72.,simulated_ack_playback_seconds=18.1,wall_seconds=dict(input=72.,playback=18.1,processing=.5,idle=0.,network=.05,cleanup=.35)))

class Preparation(unittest.TestCase):
    def test_full_plan_is_workload_bounded_and_default_disabled(self):
        plan=m.Plan();plan.validate();self.assertEqual(plan.duration,3600);self.assertGreater(plan.turns*8,3600)
        with patch.object(m,'supervise',side_effect=AssertionError('disabled')),patch.object(p,'internal_authority',side_effect=AssertionError('no child')):
            self.assertEqual(m.cli(['prepare']),2);self.assertEqual(m.cli(['_driver']),2)
        with self.assertRaises(p.Rejected):m.Plan(model_calls=999999).validate()
    def test_wall_phases_do_not_credit_arbitrary_sleep_as_media(self):
        now=[0.];timeline=m.Timeline(lambda:now[0]);now[0]=3600
        r=timeline.report();self.assertEqual(r['wall_seconds']['idle'],3600);self.assertEqual(r['declared_input_seconds'],0)
        plan,report=fixture();report['timing'].update(declared_input_seconds=0,simulated_ack_playback_seconds=0)
        with self.assertRaises(p.Rejected):m.validate_report(report,plan)
    def test_report_positive_and_counterfactuals(self):
        plan,report=fixture();m.validate_report(report,plan)
        changes=[lambda r:r.update(forced_exit=True),lambda r:r.update(collection_errors=1),lambda r:r['samples'][4]['service_process'].update(start_ticks=999),
                 lambda r:r['connections'][0].update(rst_applied=False),lambda r:r['turns'][0].update(acks=0),
                 lambda r:r['connections'][1]['release'].update(pending=1),lambda r:r['turns'][7].update(no_partial_commit=False),
                 lambda r:r['samples'].__setitem__(slice(2,-1),[]),lambda r:r['timing'].update(declared_input_seconds=90),
                 lambda r:r['turns'][2].update(status='incomplete')]
        for i,change in enumerate(changes):
            r=copy.deepcopy(report);change(r)
            with self.subTest(i=i),self.assertRaises(p.Rejected):m.validate_report(r,plan)

class AsyncPreparation(unittest.IsolatedAsyncioTestCase):
    async def test_synthetic_model_requires_actual_committed_context(self):
        model=m.MixedModel();schema=dict(properties=dict(mode={}))
        for index in (3,5,7):
            with self.subTest(index=index),self.assertRaises(p.Rejected):await model.complete('',dict(text=m.TEXTS[index],context={}),schema=schema)
        actual=dict(mode='story',rules='每人两句；飞船只能慢慢飞')
        plan=json.loads(await model.complete('',dict(text=m.TEXTS[3],context=dict(game=actual)),schema=schema))
        self.assertEqual(plan['rules'],actual['rules']);self.assertEqual(plan['action'],'continue')
    async def test_pcm_and_ack_pacing_is_byte_derived(self):
        asyncio.get_running_loop().set_debug(False)
        ticks=[100000]
        async def sleep(seconds):ticks[0]+=round(seconds*1000)
        async def observe(event):pass
        wire=m.PacedWire(NS(send=AsyncMock()),NS(),'normal_close',None,timeline=m.Timeline(lambda:ticks[0]/1000),observe=observe)
        with patch.object(m.time,'monotonic',lambda:ticks[0]/1000),patch.object(m.asyncio,'sleep',sleep):
            await wire.input();self.assertEqual(wire.timeline.input_samples,96000);self.assertEqual(wire.timeline.sent_input_samples,96000)
            self.assertEqual(wire.ws.send.call_count,302)
            raw=__import__('base64').b64encode(b'\x01\x00'*2400).decode();event=dict(pcm=raw,start=0,end=2400)
            await wire.before_ack(event);self.assertEqual(wire.timeline.played_samples,0)
            await wire.after_ack(event);self.assertEqual(wire.timeline.played_samples,2400)
            self.assertAlmostEqual(wire.timeline.report()['wall_seconds']['input'],6.)
            with self.assertRaises(p.Rejected):await wire.before_ack(dict(event,end=1200))
    async def test_shared_allowance_does_not_reset_when_configuring_new_turns(self):
        with patch.object(m,'process_identity',return_value=dict(pid=20,start_ticks=10)):
            service=m.MixedService(m.Plan())
            service.allowance.take('model')
            for step in (0,1,2):await service.dispatch(dict(op='mixed_configure',step=step,fault='normal_close'))
            self.assertEqual(service.allowance.report()['model_calls'],1)
    async def test_synthetic_pcm_has_exact_two_seconds_and_single_reservation(self):
        allowance=NS(take=lambda *args:None);speech=m.MixedSpeech(allowance,m.Plan())
        async with speech.synthesize('合成',24000) as chunks:frames=[chunk async for chunk in chunks]
        self.assertEqual(sum(map(len,frames))/48000,2.);self.assertEqual(len(frames),20);self.assertEqual(speech.tts_active,0)
