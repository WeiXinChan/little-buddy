"""Reject unsupported product PASS claims; adapter errors must fail execution."""
import hashlib
from pathlib import Path
import subprocess


def provenance():
    paths = sorted(p for p in Path('tools/v2_harness').rglob('*')
                   if p.is_file() and '__pycache__' not in p.parts)
    return {
        'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], text=True)),
        'content_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
    }


def validate_product_result(row):
    if row['status'] != 'PASS':
        return
    required = ['product_adapter', 'implementation_sha', 'evidence', 'provenance']
    if any(not row.get(key) for key in required):
        raise ValueError('product PASS lacks adapter/version/evidence/provenance')
    if row.get('scope') != 'product' or row.get('attempts', 0) <= 0:
        raise ValueError('fixture-only or zero-sample PASS')
    if row.get('failures') != 0 or row.get('errors') != 0:
        raise ValueError('failed/error attempts cannot produce PASS')
    if row.get('requires_acoustic') not in (True, False) or row.get('requires_acoustic') is None:
        raise ValueError('acoustic evidence requirement must be explicitly classified')
    if row.get('timeouts', 0) != 0:
        raise ValueError('timeouts cannot disappear from the denominator')
    if row.get('requires_acoustic') and not row.get('acoustic_observation'):
        raise ValueError('missing independent acoustic observation')


def execute(adapter, case, oracle):
    """No default/empty adapter. Oracle must raise on incorrect observations."""
    if adapter is None or not callable(adapter):
        raise ValueError('no product adapter')
    observed = adapter(case)  # exceptions deliberately propagate
    if observed is None:
        raise ValueError('adapter returned no observation')
    if oracle(observed) is not True:
        raise AssertionError('product observation violates assertion')
    return observed
