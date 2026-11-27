import sys,pathlib,unittest,copy
sys.path.insert(0,str(pathlib.Path(__file__).parent/'source'))
from scripts import v2_mixed_tls as m
from scripts import v2_persistent_tls as p
from tests.v2.test_mixed_tls_preparation import fixture
class Independent(unittest.TestCase):
    def test_delivered_turn_binding_must_match_own_connection(self):
        plan,r=fixture();r['turns'][0]['binding']='f'*64
        with self.assertRaises(p.Rejected):m.validate_report(r,plan)
    def test_connection_delivery_label_must_match_actual_fault_turn(self):
        plan,r=fixture();r['connections'][0]['status']='delivered' # ASR RST, lastturn fault-injected/0ACK
        with self.assertRaises(p.Rejected):m.validate_report(r,plan)
    def test_short_media_and_zero_sent_bytes_cannot_pad_wall_success(self):
        plan,r=fixture()
        for row in r['turns']:
            row['input_seconds']=.01
            row['playback_seconds']=.01 if row['acks'] else 0.
        inp=sum(x['input_seconds'] for x in r['turns']);play=sum(x['playback_seconds'] for x in r['turns'])
        r['timing'].update(declared_input_seconds=inp,sent_input_seconds=0.,simulated_ack_playback_seconds=play)
        r['timing']['wall_seconds'].update(input=inp,playback=play,idle=91-inp-play-.5-.05-.35)
        with self.assertRaises(p.Rejected):m.validate_report(r,plan)
    def test_cutoff_must_occur_at_actual_duration_not_earlier(self):
        plan,r=fixture();r['connections'][-1]['completed']=80.;r['turns'][-1]['completed']=80.
        with self.assertRaises(p.Rejected):m.validate_report(r,plan)
    def test_sampling_must_include_active_and_confirmed_cleanup_events(self):
        plan,r=fixture()
        self.assertFalse(any(s['event'] in {'first_audio_transport','before_cleanup','after_cleanup','turn_delivered'} for s in r['samples']))
        with self.assertRaises(p.Rejected):m.validate_report(r,plan)
    def test_active_shutdown_cannot_be_reported_confirmed(self):
        plan,r=fixture();r['shutdown'].update(active=True,quarantined=True)
        with self.assertRaises(p.Rejected):m.validate_report(r,plan)
if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Independent));sys.exit(not result.wasSuccessful())
