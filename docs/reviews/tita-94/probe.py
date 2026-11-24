import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch
from tools.v2_harness import inventory
from tools.v2_harness.evidence import provenance, validate_product_result

results = {}
base = dict(status='PASS', scope='product', product_adapter='control',
            implementation_sha='control', evidence=['control'], provenance={'control': True},
            attempts=1, failures=0, errors=0, timeouts=0,
            requires_acoustic=True, acoustic_observation='control')
for key, value in [('product_adapter', None), ('scope', 'fixture-self-test-only'),
                   ('attempts', 0), ('acoustic_observation', None)]:
    try:
        validate_product_result(dict(base, **{key: value}))
        results['reject_' + key] = False
    except ValueError:
        results['reject_' + key] = True
for name, code in {
    'wrong': 'execute(lambda c: {"muted":False}, {}, lambda o: o["muted"] is True)',
    'unavailable': 'execute(lambda c: (_ for _ in ()).throw(RuntimeError("unavailable")), {}, lambda o: True)',
    'missing': 'execute(None, {}, lambda o: True)',
    'empty': 'execute(lambda c: None, {}, lambda o: True)',
}.items():
    p = subprocess.run([sys.executable, '-c', 'from tools.v2_harness.evidence import execute; ' + code], capture_output=True, timeout=10)
    results['adapter_' + name + '_exit'] = p.returncode
with tempfile.TemporaryDirectory() as tmp:
    target = Path(tmp)
    shutil.copytree('tools/v2_harness', target / 'tools/v2_harness', ignore=shutil.ignore_patterns('__pycache__'))
    subprocess.run(['git', 'init', '-q', tmp], check=True)
    subprocess.run(['git', '-C', tmp, 'add', '.'], check=True)
    subprocess.run(['git', '-C', tmp, '-c', 'user.name=Review Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)
    import os
    cwd = os.getcwd()
    try:
        os.chdir(tmp)
        before = provenance()
        path = Path('tools/v2_harness/dialogues.json')
        path.write_bytes(path.read_bytes() + b'\n')
        after = provenance()
        results['provenance'] = dict(clean_before=not before['dirty'], dirty_after=after['dirty'], same_head=before['head']==after['head'], hash_changed=before['content_sha256'][str(path)]!=after['content_sha256'][str(path)], actual_hash_matches=after['content_sha256'][str(path)]==hashlib.sha256(path.read_bytes()).hexdigest())
    finally:
        os.chdir(cwd)
calls = []
def fake_run(argv, **kwargs):
    calls.append(dict(argv=argv, **kwargs))
    return subprocess.CompletedProcess(argv, 0, 'SYNTHETIC_PRIVATE_DEVICE_NAME' if argv[0]=='system_profiler' else 'device', 'SYNTHETIC_STDERR')
with patch.object(inventory.sys, 'platform', 'darwin'), patch.object(sys, 'argv', ['inventory', '--serial', 'SYNTHETIC_SERIAL']), patch.object(inventory.subprocess, 'run', fake_run), contextlib.redirect_stdout(io.StringIO()) as out:
    inventory.main()
results['inventory_mock'] = dict(calls=calls, serial_not_in_report='SYNTHETIC_SERIAL' not in out.getvalue(), stderr_not_in_report='SYNTHETIC_STDERR' not in out.getvalue(), private_audio_name_in_report='SYNTHETIC_PRIVATE_DEVICE_NAME' in out.getvalue())
for name, side in [('timeout', subprocess.TimeoutExpired(['synthetic'],10)), ('missing_binary', FileNotFoundError())]:
    with patch.object(inventory.subprocess, 'run', side_effect=side):
        results['inventory_' + name] = inventory.query(['synthetic'])
with patch.object(inventory.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, 'PRIVATE', 'PRIVATE')):
    results['inventory_nonzero'] = inventory.query(['synthetic'])
for name, edit in [('missing_timeouts', lambda r: r.pop('timeouts')), ('nan_attempts', lambda r: r.update(attempts=float('nan'))), ('bool_attempts', lambda r: r.update(attempts=True)), ('numeric_acoustic_false', lambda r: r.update(requires_acoustic=0, acoustic_observation=None))]:
    row = copy.deepcopy(base)
    edit(row)
    try:
        validate_product_result(row)
        results[name] = 'ACCEPTED'
    except Exception as e:
        results[name] = type(e).__name__
original = json.loads(Path('docs/testing/v2/self-test.json').read_text())
current = provenance()
results['original_hashes_match'] = original['provenance']['content_sha256'] == current['content_sha256']
results['current_provenance'] = current
Path('../review-evidence/probes.json').write_text(json.dumps(results, indent=2) + '\n')
print(json.dumps(results, indent=2))
