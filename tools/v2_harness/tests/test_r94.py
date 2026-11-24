"""Regression tests for independent review counterexamples; no device calls."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from tools.v2_harness.evidence import execute, validate_product_result, validate_report_schema
from tools.v2_harness import inventory


def row():
    return dict(id='A08', status='PASS', scope='product', attempts=1,
                failures=0, errors=0, timeouts=0, requires_acoustic=True,
                acoustic_observation={'source': 'synthetic-negative-control'})


class EvidenceRegression(unittest.TestCase):
    def test_strict_counts_reject_review_bypasses(self):
        for key in ['attempts', 'failures', 'errors', 'timeouts']:
            for value in [True, False, float('nan'), float('inf'), -float('inf'),
                          1.0, '1', None, {}, [], -1]:
                with self.subTest(key=key, value=repr(value)), self.assertRaises(ValueError):
                    validate_report_schema(dict(row(), **{key: value}))
            missing = row()
            missing.pop(key)
            with self.subTest(missing=key), self.assertRaises(ValueError):
                validate_report_schema(missing)

    def test_count_relationships_and_zero_samples(self):
        for changes in [dict(attempts=0), dict(failures=1), dict(errors=1), dict(timeouts=1),
                        dict(status='FAIL', failures=1, errors=1),
                        dict(status='NOT_RUN', attempts=1)]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_report_schema(dict(row(), **changes))
        validate_report_schema(dict(row(), status='FAIL', attempts=3, failures=1, errors=1, timeouts=1))

    def test_controlled_acoustic_policy_not_report_authored(self):
        for value in [0, 1, 'false', None, [], {}, False]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_report_schema(dict(row(), requires_acoustic=value, acoustic_observation=None))
        with self.assertRaises(ValueError):
            validate_report_schema(dict(row(), acoustic_observation=None))
        validate_report_schema(dict(row(), id='A24', requires_acoustic=False))

    def test_bad_report_shapes_and_unconditional_product_pass_disabled(self):
        for bad in [None, [], {}, {'status': []}, dict(row(), id=[]), dict(row(), id='A99')]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_product_result(bad)
        fabricated = dict(row(), product_adapter='fake', implementation_sha='a' * 40,
                          evidence=[{'source': 'claimed'}], provenance={'head': 'b' * 40})
        validate_report_schema(fabricated)
        with self.assertRaisesRegex(ValueError, 'PASS disabled'):
            validate_product_result(fabricated)

    def test_empty_invalid_observations_and_unconditional_oracle(self):
        for observed in [None, {}, [], '', {'muted': 1}, {'muted': True, 'extra': 'body'}]:
            with self.subTest(observed=observed), self.assertRaises(ValueError):
                execute(lambda c: observed, {'scenario': 'fixture.stop.v1'})
        with self.assertRaises(ValueError):
            execute(lambda c: {'muted': True}, {'scenario': 'fixture.stop.v1'}, lambda o: True)
        with self.assertRaises(ValueError):
            execute(lambda c: {'muted': True}, {}, 'fixture.stop.v1')
        with self.assertRaises(AssertionError):
            execute(lambda c: {'muted': False}, {'scenario': 'fixture.stop.v1'})


class InventoryRegression(unittest.TestCase):
    def test_anonymous_audio_white_list_and_unknown_schemas(self):
        fixture = json.loads(Path('tools/v2_harness/inventory-inputs.json').read_text())
        report = inventory.audio_summary(json.dumps(fixture['audio']))
        self.assertEqual(report, {'status': 'observed', 'devices': [
            {'id': 'audio-1', 'input_channels': 2, 'output_channels': 2, 'sample_rate_hz': 48000}]})
        rendered = json.dumps(report)
        for private in fixture['private_sentinels']:
            self.assertNotIn(private, rendered)
        for raw in ['', '{}', '[]', 'invalid', '{"SPAudioDataType": []}',
                    '{"SPAudioDataType": [{"_items": "private"}]}']:
            self.assertEqual(inventory.audio_summary(raw), inventory.UNKNOWN)

    def test_adb_output_is_filtered_empty_not_observed(self):
        adb = ['adb', '-s', 'SYNTHETIC_SERIAL']
        for suffix in [['get-state']] + [['shell', 'getprop', p] for p in inventory.PROPS]:
            for raw in [None, '', 'SYNTHETIC_PRIVATE_NAME', '192.0.2.1', 'UID-SYNTHETIC']:
                with self.subTest(suffix=suffix, raw=raw), patch.object(inventory, '_capture', return_value=raw):
                    self.assertEqual(inventory.query(adb + suffix), inventory.UNKNOWN)
        for prop, raw, value in [('ro.product.model', 'PKW110', 'PKW110'),
                                 ('ro.build.version.release', '16', '16'),
                                 ('ro.build.version.sdk', '36', 36)]:
            with patch.object(inventory, '_capture', return_value=raw):
                self.assertEqual(inventory.query(adb + ['shell', 'getprop', prop]),
                                 {'status': 'observed', 'value': value})

    def test_main_mocked_six_command_allowlist_and_report_cap(self):
        calls = []
        fixture = json.loads(Path('tools/v2_harness/inventory-inputs.json').read_text())
        def captured(argv):
            calls.append(argv)
            self.assertTrue(inventory._allowed(argv))
            return json.dumps(fixture['audio']) if argv[0] == 'system_profiler' else 'SYNTHETIC_PRIVATE_NAME'
        with patch.object(inventory, '_capture', side_effect=captured), \
                patch.object(sys, 'argv', ['inventory', '--serial', 'SYNTHETIC_SERIAL']), \
                patch.object(inventory.sys, 'platform', 'darwin'), contextlib.redirect_stdout(io.StringIO()) as out:
            inventory.main()
        self.assertEqual(len(calls), 6)
        self.assertLessEqual(len(out.getvalue().encode()), inventory.MAX_REPORT_BYTES + 1)
        for private in fixture['private_sentinels'] + ['SYNTHETIC_SERIAL', 'SYNTHETIC_PRIVATE_NAME']:
            self.assertNotIn(private, out.getvalue())

    def test_bounded_capture_no_shell_stderr_timeout_and_errors(self):
        real_popen = subprocess.Popen
        def run_fake(code, timeout=inventory.TIMEOUT):
            def spawn(argv, **kwargs):
                self.assertTrue(inventory._allowed(argv))
                self.assertIs(kwargs['shell'], False)
                self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)
                return real_popen([sys.executable, '-c', code], **kwargs)
            with patch.object(inventory.subprocess, 'Popen', side_effect=spawn):
                return inventory._capture(['adb', '-s', 'SYNTHETIC_SERIAL', 'get-state'], timeout=timeout)
        self.assertEqual(run_fake('print("device")'), 'device')
        self.assertIsNone(run_fake('pass'))
        self.assertIsNone(run_fake('import sys; print("PRIVATE", file=sys.stderr); sys.exit(1)'))
        self.assertIsNone(run_fake('import sys; sys.stdout.buffer.write(b"x" * 65537)'))
        self.assertIsNone(run_fake('import time; time.sleep(1)', timeout=0.01))
        self.assertIsNone(run_fake('import sys; sys.stdout.buffer.write(b"\\xff")'))
        with patch.object(inventory.subprocess, 'Popen', side_effect=OSError('PRIVATE_EXCEPTION')):
            self.assertIsNone(inventory._capture(['adb', '-s', 'SYNTHETIC_SERIAL', 'get-state']))
        with patch.object(inventory.subprocess, 'Popen') as popen:
            self.assertIsNone(inventory._capture(['adb', 'devices']))
            self.assertIsNone(inventory._capture(['multica', 'daemon', 'stop']))
            popen.assert_not_called()
        self.assertEqual(inventory.TIMEOUT, 10)


if __name__ == '__main__':
    unittest.main()
