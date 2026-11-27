"""Complete positive and scoped counterfactuals, never native/90s workloads."""
import copy,importlib.util,json,unittest
from pathlib import Path
from tests.v2 import test_mixed_tls_preparation as fixtures
from scripts import v2_mixed_tls as m

class Association(unittest.TestCase):
    def setUp(self):
        self.plan,self.base=fixtures.fixture();m.validate_report(self.base,self.plan)
    def reject(self,change):
        r=copy.deepcopy(self.base);change(r)
        with self.assertRaises(m.p.Rejected):m.validate_report(r,self.plan)
    def test_original_delivered_binding_mutation_on_complete_positive(self):
        self.reject(lambda r:r['turns'][0].update(binding='f'*64))
    def test_original_fault_label_mutation_on_complete_positive(self):
        self.reject(lambda r:r['connections'][0].update(status='delivered'))
    def test_original_tiny_media_idle_mutation_on_complete_positive(self):
        def short(r):
            for t in r['turns']:t.update(input_seconds=.01,playback_seconds=.01 if t['acks'] else 0.)
            inp=sum(t['input_seconds'] for t in r['turns']);play=sum(t['playback_seconds'] for t in r['turns'])
            r['timing'].update(declared_input_seconds=inp,sent_input_seconds=0.,simulated_ack_playback_seconds=play)
            r['timing']['wall_seconds'].update(input=inp,playback=play,idle=91-inp-play-.5-.05-.35)
        self.reject(short)
    def test_small_input_with_consistent_counters_and_wall_totals_still_rejects(self):
        def shrink(r):
            row=r['turns'][0];row['media'].update(sent=320,paced=320,accepted=320);row['input_seconds']=.02
            next(s for s in r['samples'] if s['event']=='input_finished' and s['turn_index']==0)['capture_bytes']=640
            for key in ('declared_input_seconds','sent_input_seconds'):r['timing'][key]-=5.98
            r['timing']['wall_seconds']['input']-=5.98;r['timing']['wall_seconds']['idle']+=5.98
        self.reject(shrink)
    def test_small_output_with_consistent_acks_and_wall_totals_still_rejects(self):
        def shrink(r):
            row=r['turns'][0];row['media'].update(received=2400,acked=2400,ack_head=2400);row.update(frames=1,acks=1,server_head=2400,playback_seconds=.1)
            next(s for s in r['samples'] if s['event']=='turn_delivered' and s['turn_index']==0)['head']=2400
            r['connections'][0]['frames']-=19;r['connections'][0]['acks']-=19
            r['timing']['simulated_ack_playback_seconds']-=1.9;r['timing']['wall_seconds']['playback']-=1.9;r['timing']['wall_seconds']['idle']+=1.9
        self.reject(shrink)
    def test_original_early_cutoff_mutation_on_complete_positive(self):
        def early(r):r['connections'][-1]['completed']=80.;r['turns'][-1]['completed']=80.
        self.reject(early)
    def test_event_removal_from_complete_positive_rejects(self):
        def remove(r):
            r['samples']=[s for s in r['samples'] if s['event'] not in {'first_audio_transport','before_cleanup','after_cleanup','turn_delivered'}]
            self.assertFalse(any(s['event'] in {'first_audio_transport','before_cleanup','after_cleanup','turn_delivered'} for s in r['samples']))
        self.reject(remove)
    def test_wrong_schedule_context_or_media_counters_reject(self):
        for change in (lambda r:r['turns'][1].update(step=5),lambda r:r['turns'][2].update(fault='asr_rst'),
                       lambda r:r['turns'][0].update(played_count=9),lambda r:r['turns'][1].update(played_anchor='f'*64),
                       lambda r:r['turns'][0]['media'].update(accepted=320),lambda r:r['turns'][0]['media'].update(acked=2400),
                       lambda r:r['timing'].update(sent_input_seconds=0),lambda r:r['connections'][0].update(acks=0)):
            with self.subTest(change=change):self.reject(change)
    def test_event_value_indices_order_and_cutoff_ownership_reject(self):
        def edit(event,**fields):
            def change(r):next(s for s in r['samples'] if s['event']==event).update(fields)
            return change
        for change in (edit('first_audio_transport',generation=False),edit('first_audio_transport',pending_audio=0),
                       edit('input_finished',capture_bytes=640),edit('after_cleanup',pending=1),
                       edit('after_cleanup',active=True),edit('turn_delivered',turn_index=11),
                       lambda r:r['cutoff'].update(expired=False),lambda r:r['cutoff'].update(owner='inner_response'),
                       lambda r:r['turns'][-1].update(cancelled_at=80),lambda r:r['connections'][-1].update(cancelled_at=80)):
            with self.subTest(change=change):self.reject(change)
    def test_partial_input_is_real_buffered_count_not_a_manufactured_full_input(self):
        last=self.base['turns'][-1]
        self.assertLess(last['media']['paced'],96000);self.assertEqual(last['media']['sent']-last['media']['paced'],320)
        self.assertIsNone(last['input_finished']);self.assertFalse(any(s['event']=='input_finished' and s['turn_index']==11 for s in self.base['samples']))
        self.reject(lambda r:r['turns'][-1]['media'].update(accepted=0))

class Observation(unittest.IsolatedAsyncioTestCase):
    async def test_native_capture_observation_is_not_replaced_with_expected_samples(self):
        import asyncio
        from types import SimpleNamespace as NS
        from unittest.mock import patch,AsyncMock
        asyncio.get_running_loop().set_debug(False);ticks=[100000];events=[]
        async def sleep(seconds):ticks[0]+=round(seconds*1000)
        async def observe(event):events.append(event)
        wire=m.PacedWire(NS(send=AsyncMock()),NS(call=AsyncMock(return_value=dict(state=dict(capture_bytes=640)))),'normal_close',None,timeline=m.Timeline(lambda:ticks[0]/1000),observe=observe)
        with patch.object(m.time,'monotonic',lambda:ticks[0]/1000),patch.object(m.asyncio,'sleep',sleep):
            with self.assertRaises(m.p.Rejected):await wire.input()
        self.assertEqual(wire.accepted,320);self.assertEqual(wire.sent,96000);self.assertNotIn('input_finished',events)
    async def test_duplicate_or_malformed_pcm_cannot_inflate_observed_received_or_acks(self):
        import base64
        from types import SimpleNamespace as NS
        async def observe(event):pass
        wire=m.PacedWire(NS(),NS(),'normal_close',None,timeline=m.Timeline(),observe=observe)
        event=dict(pcm=base64.b64encode(b'\x01\x00'*2400).decode(),start=0,end=2400,segment='synthetic')
        await wire.on_audio(event)
        with self.assertRaises(m.p.Rejected):await wire.on_audio(event)
        self.assertEqual(wire.received,2400);self.assertEqual(wire.ack_samples,0)
        with self.assertRaises(m.p.Rejected):await wire.on_audio(dict(event,segment='other',end=999))
