"""Persist R94 negative controls. All inventory commands are mocked."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from tools.v2_harness import inventory
from tools.v2_harness.evidence import provenance, validate_product_result, validate_report_schema


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    base = dict(id='A08', status='PASS', scope='product', product_adapter='synthetic-fake',
                implementation_sha='synthetic-fake', evidence=['synthetic-fake'],
                provenance={'source': 'synthetic-fake'}, attempts=1, failures=0,
                errors=0, timeouts=0, requires_acoustic=True,
                acoustic_observation={'source': 'synthetic-fake'})
    rows = {}
    missing = dict(base)
    missing.pop('timeouts')
    rows['missing_timeouts'] = missing
    for name, changes in [
        ('nan_attempts', {'attempts': float('nan')}), ('infinite_attempts', {'attempts': float('inf')}),
        ('bool_attempts', {'attempts': True}), ('string_attempts', {'attempts': '1'}),
        ('zero_samples', {'attempts': 0}), ('numeric_acoustic_false', {'requires_acoustic': 0}),
        ('override_acoustic', {'requires_acoustic': False, 'acoustic_observation': None}),
        ('missing_acoustic', {'acoustic_observation': None}), ('fixture_scope', {'scope': 'fixture-self-test-only'}),
        ('inconsistent_counts', {'failures': 1, 'errors': 1}),
    ]:
        rows[name] = dict(base, **changes)
    controls = {}
    for name, row in rows.items():
        try:
            validate_report_schema(row)
            controls[name] = False
        except ValueError:
            controls[name] = True
    try:
        validate_product_result(base)
        controls['fabricated_product_pass_disabled'] = False
    except ValueError:
        controls['fabricated_product_pass_disabled'] = True
    exits = {}
    for name, expression in {
        'wrong': 'lambda c: {"muted":False}',
        'unavailable': 'lambda c: (_ for _ in ()).throw(RuntimeError("synthetic-error"))',
        'missing': 'None', 'empty_dict': 'lambda c: {}', 'empty_list': 'lambda c: []',
        'invalid_schema': 'lambda c: {"muted":1}',
    }.items():
        code = ('from tools.v2_harness.evidence import execute; execute(' + expression
                + ', {"scenario":"fixture.stop.v1"})')
        p = subprocess.run([sys.executable, '-c', code], capture_output=True, timeout=10)
        exits[name] = p.returncode
        controls['adapter_' + name] = p.returncode != 0
    fixture = json.loads(Path('tools/v2_harness/inventory-inputs.json').read_text())
    calls = []
    def capture(argv):
        calls.append(argv)
        return json.dumps(fixture['audio']) if argv[0] == 'system_profiler' else 'SYNTHETIC_PRIVATE_DEVICE_NAME'
    with patch.object(inventory, '_capture', side_effect=capture), \
            patch.object(sys, 'argv', ['inventory', '--serial', 'SYNTHETIC_SERIAL']), \
            patch.object(inventory.sys, 'platform', 'darwin'), contextlib.redirect_stdout(io.StringIO()) as out:
        inventory.main()
    text = out.getvalue()
    controls['six_allowlisted_commands_mocked'] = len(calls) == 6 and all(inventory._allowed(c) for c in calls)
    controls['private_names_uids_serials_addresses_absent'] = all(
        private not in text for private in fixture['private_sentinels'] + ['SYNTHETIC_SERIAL'])
    controls['bounded_summary'] = len(text.encode()) <= inventory.MAX_REPORT_BYTES + 1
    report = {'scope': 'synthetic-negative-controls-only', 'provenance': provenance(),
              'controls': controls, 'control_count': len(controls),
              'failed_controls': [k for k, ok in controls.items() if not ok],
              'adapter_exit_codes': exits, 'mock_inventory': json.loads(text),
              'product_attempts': 0, 'limitations': ['No device calls; no product execution; no acoustic observation']}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    return int(bool(report['failed_controls']))


if __name__ == '__main__':
    raise SystemExit(main())
