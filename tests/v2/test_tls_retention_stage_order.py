"""Light JSON fixtures and read-only historical report; no worker/network."""
import copy,unittest
from tests.v2 import test_tls_retention_validation as fixtures
from scripts import v2_tls_retention as m

class StageOrder(unittest.TestCase):
    def mutate(self,change):
        def mutation(r,s):
            change(r)
            samples=r['resource_samples'];r['observations']=len(samples)
            s['observations']=s['retained_samples']=len(samples)
            r['resource_trends']={k:dict(first=samples[0][k],last=samples[-1][k],maximum=max(row[k] for row in samples),maximum_kind='observed_sample_maximum') for k in m.METRICS}
        return fixtures.Validation().validate_mutation(mutation)
    def test_reversed_adjacent_anchors_and_conflicting_repetition(self):
        anchors=['attempt_started','initial','before_network_fault','after_network_fault','before_transport_cleanup','after_transport_cleanup','attempt_finished']
        for a,b in zip(anchors,anchors[1:]):
            def reverse(r):
                rows=r['resource_samples'];x=next(v for v in rows if v['phase']==a);y=next(v for v in rows if v['phase']==b)
                x['phase'],y['phase']=y['phase'],x['phase']
            with self.subTest(a=a,b=b),self.assertRaises(m.Rejected):self.mutate(reverse)
        for phase in ('initial','before_network_fault','after_network_fault','before_transport_cleanup'):
            def duplicate(r):
                rows=r['resource_samples'];i=next(i for i,v in enumerate(rows) if v['phase']==phase)
                rows.insert(i,copy.deepcopy(rows[i]))
            with self.subTest(phase=phase),self.assertRaises(m.Rejected):self.mutate(duplicate)
    def test_repeated_activity_periodic_and_two_cleanup_callbacks_are_valid(self):
        def insert(r):
            rows=r['resource_samples']
            for phase in ('operation_started','before_network_fault','after_transport_cleanup'):
                i=next(i for i,v in enumerate(rows) if v['phase']==phase)
                extra=copy.deepcopy(rows[i]);rows.insert(i,extra)
                if phase=='before_network_fault':extra['phase']='periodic'
        self.mutate(insert)
    def test_cleanup_callback_cannot_precede_cleanup_begin(self):
        def move(r):
            rows=r['resource_samples'];i=next(i for i,v in enumerate(rows) if v['phase']=='before_transport_cleanup')
            extra=copy.deepcopy(rows[i]);extra['phase']='after_transport_cleanup';rows.insert(i,extra)
        with self.assertRaises(m.Rejected):self.mutate(move)
    def test_attempt_times_cannot_be_detached_from_sample_windows(self):
        def detach(r):
            for rows in (r['attempts'],r['connection_ledger']):rows[-1]['completed_seconds']-=.03
        with self.assertRaises(m.Rejected):self.mutate(detach)
