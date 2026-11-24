import copy
from dataclasses import replace
import tempfile
from pathlib import Path
import unittest
import wave
from tools.v2_harness.evidence import execute, provenance, validate_product_result

from tools.v2_harness.lab import (
    Clock, DAY, Event, FaultBudget, Handle, Management, Material, Playback, Protocol,
    assert_no_body, checked_effect, write_signal,
)


class InfrastructureTests(unittest.TestCase):
    def test_injected_network_quota_timeout_and_immutable_retry_budget(self):
        c = Clock()
        budget = FaultBudget(c)
        c.advance(14)
        self.assertTrue(budget.fault('network')['retry'])
        self.assertFalse(budget.fault('timeout')['retry'])
        self.assertEqual(budget.deadline, 15)
        for category in ['quota', 'close']:
            self.assertFalse(FaultBudget(c).fault(category)['retry'])
        fresh = FaultBudget(c)
        c.advance(15)
        self.assertFalse(fresh.fault('network')['retry'])
        self.assertFalse(FaultBudget(c).fault('network', idempotent=False)['retry'])

    def test_evidence_rejects_unsupported_product_pass(self):
        valid = dict(status='PASS', scope='product', product_adapter='synthetic-negative-control',
                     implementation_sha='synthetic-version', evidence=['synthetic-observation'],
                     provenance={'content_sha256': 'synthetic'}, attempts=1, failures=0,
                     errors=0, requires_acoustic=True, acoustic_observation='synthetic-control')
        validate_product_result(valid)  # validator control, not a product report
        for key, value in [('product_adapter', None), ('scope', 'fixture-self-test-only'),
                           ('attempts', 0), ('acoustic_observation', None), ('failures', 1),
                           ('errors', 1), ('evidence', []), ('provenance', {}),
                           ('requires_acoustic', None), ('timeouts', 1)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_product_result(dict(valid, **{key: value}))

    def test_broken_missing_empty_and_wrong_adapters_fail_executor(self):
        def broken(case):
            raise RuntimeError('synthetic unavailable adapter')
        for adapter, exception in [(None, ValueError), (lambda c: None, ValueError),
                                   (broken, RuntimeError), (lambda c: {'muted': False}, AssertionError)]:
            with self.subTest(adapter=adapter), self.assertRaises(exception):
                execute(adapter, {}, lambda o: o['muted'] is True)
        self.assertEqual(execute(lambda c: {'muted': True}, {}, lambda o: o['muted'] is True),
                         {'muted': True})

    def test_wrong_adapter_causes_process_failure(self):
        import subprocess
        import sys
        p = subprocess.run([sys.executable, '-c',
                            'from tools.v2_harness.evidence import execute; '
                            'execute(lambda case: {"muted": False}, {}, '
                            'lambda observed: observed["muted"] is True)'],
                           capture_output=True, text=True, timeout=10)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('AssertionError', p.stderr)

    def test_provenance_hashes_actual_tools_and_input(self):
        import hashlib
        p = provenance()
        self.assertIsInstance(p['dirty'], bool)
        for path in ['tools/v2_harness/run.py', 'tools/v2_harness/dialogues.json']:
            self.assertEqual(p['content_sha256'][path], hashlib.sha256(Path(path).read_bytes()).hexdigest())

    def test_clock_order_duplicate_late_and_boundary(self):
        c, events = Clock(), []
        for delay, value in [(3, 'late'), (1, 'first'), (1, 'duplicate')]:
            c.after(delay, lambda v=value: events.append((c.mono, v)))
        c.advance(1)
        self.assertEqual(events, [(1, 'first'), (1, 'duplicate')])
        c.advance(2)
        self.assertEqual(events[-1], (3, 'late'))
        with self.assertRaises(ValueError):
            c.advance(-1)

    def test_protocol_reorder_duplicate(self):
        p = Protocol()
        self.assertFalse(p.accept(Event(sequence=1)))
        self.assertTrue(p.accept(Event()))
        self.assertFalse(p.accept(Event()))
        self.assertTrue(p.accept(Event(sequence=1)))

    def test_protocol_all_identity_dimensions_and_late_callbacks(self):
        for field, value in [('connection', 2), ('session', 'other'), ('turn', 2),
                             ('output', 2), ('task', 'other')]:
            with self.subTest(field=field):
                self.assertFalse(Protocol().accept(replace(Event(), **{field: value})))
        p, c = Protocol(), Clock()
        for kind in ['model', 'audio', 'image', 'tool', 'ack', 'safety', 'timer']:
            c.after(1, lambda k=kind: self.assertFalse(p.accept(Event(kind=k))))
        p.cancel()
        c.advance(1)
        self.assertEqual(p.effects, [])
        self.assertTrue(p.accept(p.current))
        self.assertFalse(p.accept(replace(p.current, kind='unknown')))

    def test_cancel_close_failure_and_queue_bound(self):
        for cancel, close in [(False, False), (True, False), (False, True), (True, True)]:
            with self.subTest(cancel=cancel, close=close):
                h = Handle(cancel, close)
                self.assertTrue(h.enqueue('a'))
                self.assertTrue(h.enqueue('b'))
                self.assertFalse(h.enqueue('overflow'))
                self.assertEqual(h.cancel(), not (cancel or close))
                self.assertTrue(h.muted)
                self.assertEqual(h.queue, [])
                self.assertEqual(h.unavailable, cancel or close)

    def test_f03_reset_old_ack_does_not_reveal(self):
        for reason in ['flush', 'stop', 'rebuild', 'wrap', 'route-loss']:
            with self.subTest(reason=reason):
                p = Playback()
                p.send('public', 100)
                self.assertTrue(p.ack(0, 'public', 100))
                p.send('secret', 200)
                self.assertFalse(p.ack(0, 'secret', 150))
                p.reset(reason)
                p.send('new', 200)
                self.assertFalse(p.ack(0, 'secret', 200))
                self.assertNotIn('secret', p.confirmed)
                self.assertIn('public', p.confirmed)
                if reason == 'route-loss':
                    self.assertFalse(p.ack(p.stream, 'new', 200))
                    p.route = True
                self.assertTrue(p.ack(p.stream, 'new', 200))

    def test_playback_contiguous_prefix_and_duplicate(self):
        p = Playback()
        p.send('a', 100)
        p.send('b', 200)
        self.assertFalse(p.ack(0, 'b', 200))
        self.assertTrue(p.ack(0, 'a', 100))
        self.assertFalse(p.ack(0, 'a', 100))
        self.assertTrue(p.ack(0, 'b', 200))

    def test_f01_exit_background_late_callback(self):
        for cause in ['background', 'lock', 'permission-revoked', 'recognizer-failed']:
            with self.subTest(cause=cause):
                m = Management()
                m.enter()
                old = m.epoch
                m.buffer.append('synthetic-management-talk')
                self.assertTrue(m.command(old, 'exit'))
                m.exit()  # inactive/failure: same release contract
                self.assertFalse(m.command(old, 'exit'))
                self.assertFalse(m.mic)
                self.assertEqual(m.buffer + m.context, [])
                self.assertEqual(m.page, 'idle')

    def test_f02_auth_binding_expiry_and_one_use(self):
        m = Management()
        m.enter()
        good = (m.pair, 'initialize', m.epoch, 'synthetic-challenge', 10, True)
        for index, wrong in [(0, 'other-device'), (1, 'recover'), (2, 0), (4, 0), (5, False)]:
            bad = list(good)
            bad[index] = wrong
            self.assertFalse(m.authenticate(tuple(bad), 'initialize', 0))
        self.assertTrue(m.authenticate(good, 'initialize', 0))
        self.assertFalse(m.authenticate(good, 'initialize', 0))
        m.exit()
        m.enter()
        self.assertFalse(m.authenticate(good, 'initialize', 0))
        fresh_process = Management()
        self.assertFalse(fresh_process.authenticate(good, 'initialize', 0))
        m.pair = ''
        self.assertFalse(m.authenticate(good, 'initialize', 0))

    def test_f04_immediate_revoke_all_copies_failed_delete(self):
        for submitted in [None, 0]:
            m = Material('device-a', 0, submitted=submitted)
            self.assertTrue(m.access('device-a', 1))
            self.assertFalse(m.access('device-b', 1))
            m.failed = {'download', 'backup'}
            m.withdraw(2)
            self.assertFalse(m.access('device-a', 2))  # includes old signed-link access
            m.withdraw(3)
            self.assertEqual(m.withdrawal, 2)
            self.assertFalse(m.sweep(2))
            self.assertEqual(m.copies, m.failed)
            m.failed.clear()
            self.assertTrue(m.sweep(3))

    def test_f04_earlier_deadline_exact_boundary(self):
        for withdrawal, expected in [(DAY, 2 * DAY), (7 * DAY - 3600, 7 * DAY)]:
            m = Material('a', 0, submitted=0)
            m.withdraw(withdrawal)
            self.assertEqual(m.expiry, expected)
            self.assertFalse(m.access('a', expected))
        m = Material('a', 0, submitted=0)
        self.assertTrue(m.access('a', 7 * DAY - 1))
        self.assertFalse(m.access('a', 7 * DAY))
        self.assertTrue(m.sweep(7 * DAY))

    def test_f05_expired_ledger_old_snapshot_orphan(self):
        m = Material('a', 0, submitted=0)
        snapshot = copy.deepcopy(m)
        m.withdraw(DAY)
        self.assertTrue(m.sweep(DAY))
        self.assertFalse(snapshot.restore(7 * DAY))  # no deletion ledger available
        self.assertEqual(snapshot.copies, set())
        orphan = Material('a', 0)
        self.assertTrue(orphan.access('a', 3599))
        self.assertFalse(orphan.access('a', 3600))
        self.assertTrue(orphan.sweep(3600))

    def test_safety_failure_no_segment_image_tool_effect(self):
        for kind in ['audio', 'image', 'tool']:
            for safety in [False, None, 'timeout']:
                self.assertFalse(checked_effect(safety, kind))
            self.assertTrue(checked_effect(True, kind))

    def test_body_leak_sentinel_positive_and_negative_controls(self):
        sentinel = 'SYNTHETIC_BODY_SENTINEL_80'
        assert_no_body(['stage=cancelled', 'error=timeout'], sentinel)
        for channel in ['log', 'exception', 'cache', 'monitor', 'crash']:
            with self.subTest(channel=channel), self.assertRaises(AssertionError):
                assert_no_body([channel + sentinel], sentinel)

    def test_signal_has_source_and_sample_intervals(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'signal.wav'
            meta = write_signal(path)
            self.assertIn('not-speech', meta['source'])
            with wave.open(str(path), 'rb') as audio:
                self.assertEqual(audio.getnframes(), 16000)
                self.assertEqual(audio.getframerate(), 16000)


if __name__ == '__main__':
    unittest.main()
