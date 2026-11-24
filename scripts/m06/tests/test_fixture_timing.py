import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixture_timing import FixtureTiming


class TimingTest(unittest.TestCase):
    def probe(self, run):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        ticks = iter(range(100, 1000))
        return FixtureTiming(dict(nonce='owned-fixture', sha256='fixture-hash',
                                  request_guest_elapsed_ms=1234), Path(directory.name),
                             run, lambda: next(ticks))

    def test_guest_boottime_is_bracketed_not_host_clock(self):
        def run(args, **kwargs):
            self.assertEqual(args, ['adb', 'shell', 'cat', '/proc/uptime'])
            self.assertEqual(kwargs['timeout'], 2)
            return subprocess.CompletedProcess(args, 0, '51.59 89.00\n', '')
        p = self.probe(run)
        p.bridge('PRE_INJECT')
        e = json.loads(p.path.read_text())['events'][-1]
        self.assertEqual(e['guest_boottime_ms'], 51590)
        self.assertLess(e['host_before_ns'], e['host_after_ns'])
        self.assertEqual(e['quantization_ms'], 10)

    def test_bad_output_and_failure_keep_prior_stages_without_content(self):
        p = self.probe(lambda *a, **kw: subprocess.CompletedProcess(a, 1, 'SECRET', 'SECRET'))
        p.step('HASH_VERIFIED')
        p.bridge('PRE_INJECT')
        self.assertNotIn('SECRET', p.path.read_text())
        self.assertEqual(p.data['events'][-1]['clock_status'], 'UNAVAILABLE')
        def fail(*a, **kw):
            raise subprocess.TimeoutExpired('SECRET', 2, stderr='SECRET')
        p.run = fail
        p.bridge('POST_INJECT')
        self.assertEqual(len(p.data['events']), 4)
        self.assertNotIn('SECRET', p.path.read_text())
