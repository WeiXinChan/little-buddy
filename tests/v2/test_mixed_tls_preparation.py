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
    """Complete metadata-only positive: 1 full ASR-RST block + partial recovery.
    It is never presented as an executed 90-second run.
    """
    plan=m.Plan(duration=90);turns=[];samples=[]
    starts=[.1+i*8.04 for i in range(7)]+[56.38,62.52,70.56,76.9,84.94]
    bindings=['a'*64,'c'*64];played=[0,0]
    def sample(event,when,connection=-1,turn=-1,**changes):
        r=dict(event=event,elapsed=round(when,6),connection_index=connection,turn_index=turn,
            service_process=dict(pid=20,start_ticks=100),client_process=dict(pid=10,start_ticks=90),
            service_resources=dict(backend_rss_bytes=100,backend_fds=7,backend_threads=1,asyncio_tasks=3),
            client_resources=dict(backend_rss_bytes=120,backend_fds=10,backend_threads=1,asyncio_tasks=4),allowance=dict(ALLOWANCE),
            pending=0,retired=0,generation=False,asr_active=0,tts_active=0,capture_bytes=0,active=False,pending_audio=0,
            binding=None,same_session=False,played_count=0,played_anchor=None,head=0,state_hash=None,game=None,rules_hash=None,roles_hash=None)
        r.update(changes);samples.append(r);return r
    sample('before_warmup',0)
    for t in range(0,91,5):sample('periodic',t)
    for i,start in enumerate(starts):
        connection=0 if i<10 else 1;local=i if i<10 else i-10;step=local if local<7 else 7 if local<9 else 8
        fault='playback_stop' if i==7 else 'asr_rst' if i==9 else 'normal_close'
        status='interrupted' if i==7 else 'fault_injected' if i==9 else 'duration_cutoff' if i==11 else 'delivered'
        complete=i!=11;sent=96000 if complete else 80960;paced=96000 if complete else 80640
        rx=0 if i in (9,11) else 4800 if i==7 else 48000;acked=2400 if i==7 else 0 if i in (9,11) else 48000
        end=round(start+6,6) if complete else None;completed=round(start+(6.12 if i==7 else 6.02 if i==9 else 8.02),6) if complete else 90.001
        row=dict(index=i,connection_index=connection,step=step,fault=fault,status=status,elapsed=round(start-.01,6),completed=completed,
            input_started=round(start,6),input_finished=end,frames=rx//2400,acks=acked//2400,media=dict(sent=sent,paced=paced,accepted=sent,received=rx,acked=acked,ack_head=acked),
            input_seconds=paced/16000,playback_seconds=acked/24000,first_audio_seconds=.005 if acked else None,binding=bindings[connection],same_session=True)
        source=dict(active=True,binding=row['binding'],same_session=True,played_count=played[connection],played_anchor='b'*64 if played[connection] else None)
        sample('input_started',start-.005,connection,i,**source)
        if complete:sample('input_finished',end+.001,connection,i,capture_bytes=192000,**source)
        if acked:sample('first_audio_transport',end+.006,connection,i,generation=True,pending_audio=1,**source)
        if status=='delivered':
            played[connection]+=1;row.update(game=m.MODES[step],played_count=played[connection],played_anchor='b'*64,server_head=48000,
                state_hash=m.p.digest(['state',i]),rules_hash=m.p.digest(['rules',step]),roles_hash=m.p.digest(['roles',step]))
            observed={k:row[k] for k in ('binding','same_session','played_count','played_anchor','game','state_hash','rules_hash','roles_hash')}
            sample('turn_delivered',completed-.001,connection,i,active=True,head=48000,**observed)
        elif status=='interrupted':
            row['no_partial_commit']=True
            sample('stop_confirmed',completed-.001,connection,i,**source)
        elif status=='duration_cutoff':row['cancelled_at']=90.001
        turns.append(row)
    def release(index):return dict(cleanup_confirmed=True,transport_closed=True,pending=0,retired=0,errors=0,heard=0,pending_audio=0,active=False,quarantined=False,constructed=index+1,finished=True,binding=bindings[index],same_session=True)
    rows=[dict(index=0,started=0.,completed=76.7,fault='asr_rst',status='fault_injected',turn_start=0,turn_end=10,cleanup_confirmed=True,client_cleanup=True,release=release(0),binding=bindings[0],new_session=True,frames=sum(t['frames'] for t in turns[:10]),acks=sum(t['acks'] for t in turns[:10]),old_ack_checked=True,cross_connection_old_ack_checked=None,rst_applied=True),
          dict(index=1,started=76.8,completed=90.25,cancelled_at=90.001,fault='normal_close',status='duration_cutoff',turn_start=10,turn_end=12,cleanup_confirmed=True,client_cleanup=True,release=release(1),binding=bindings[1],new_session=True,frames=turns[10]['frames'],acks=turns[10]['acks'])]
    sample('before_cleanup',76.6,0,9,binding=bindings[0],same_session=True)
    sample('after_cleanup',76.71,0,9);sample('after_warmup',76.72,0,9)
    sample('before_cleanup',90.05,1,11,active=True,binding=bindings[1],same_session=True,capture_bytes=161920,played_count=1,played_anchor='b'*64)
    sample('after_cleanup',90.26,1,11);sample('final',90.4,1,11);samples.sort(key=lambda s:s['elapsed'])
    shutdown=dict(pending=0,retired=0,errors=0,heard=0,pending_audio=0,played_count=0,capture_bytes=0,asr_active=0,tts_active=0,binding=None,played_anchor=None,state_hash=None,game=None,rules_hash=None,roles_hash=None,active=False,quarantined=False,finished=True,generation=False,same_session=False,recognition_active=False,constructed=2,process=dict(pid=20,start_ticks=100),allowance=dict(ALLOWANCE))
    inp=sum(t['media']['paced'] for t in turns)/16000;sent=sum(t['media']['sent'] for t in turns)/16000;play=sum(t['media']['acked'] for t in turns)/24000
    wall=dict(input=inp,playback=play,processing=.6,network=.05,cleanup=.5,idle=90.4-inp-play-1.15)
    return plan,dict(status='duration_collected_not_acceptance',limits=asdict(plan),duration=90,collection_errors=0,cleanup_confirmed=True,forced_exit=False,service_exit=0,cloud=False,device=False,acoustic=False,acceptance=False,gc_forced=False,connections=rows,turns=turns,samples=samples,rounds=[],service_pid=20,driver_pid=10,shutdown=shutdown,cutoff=dict(owner='outer_work_window',expired=True,deadline_elapsed=90,observed_elapsed=90.3),timing=dict(elapsed_seconds=90.4,declared_input_seconds=inp,sent_input_seconds=sent,simulated_ack_playback_seconds=play,wall_seconds=wall))

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
        wire=m.PacedWire(NS(send=AsyncMock()),NS(call=AsyncMock(return_value=dict(state=dict(capture_bytes=192000)))),'normal_close',None,timeline=m.Timeline(lambda:ticks[0]/1000),observe=observe)
        with patch.object(m.time,'monotonic',lambda:ticks[0]/1000),patch.object(m.asyncio,'sleep',sleep):
            await wire.input();self.assertEqual(wire.timeline.input_samples,96000);self.assertEqual(wire.timeline.sent_input_samples,96000)
            self.assertEqual(wire.ws.send.call_count,302)
            raw=__import__('base64').b64encode(b'\x01\x00'*2400).decode();event=dict(pcm=raw,start=0,end=2400,segment='synthetic');await wire.on_audio(event)
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
