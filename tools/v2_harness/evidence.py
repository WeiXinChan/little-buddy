"""Reject unsupported product PASS claims; adapter errors must fail execution."""
import hashlib
from pathlib import Path
import subprocess
from types import MappingProxyType

# Controlled policy, not a flag supplied by a report. Changes require review.
SCENARIOS = MappingProxyType({f'A{i:02}': i in {2, 6, 7, 8, 9, 13, 32, 35, 36}
                              for i in range(1, 39)})


def provenance():
    paths = sorted(p for p in Path('tools/v2_harness').rglob('*')
                   if p.is_file() and '__pycache__' not in p.parts)
    return {
        'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], text=True)),
        'content_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
    }


def validate_report_schema(row):
    """Structural validation only; this is never evidence of product execution."""
    if (type(row) is not dict or type(row.get('status')) is not str
            or row['status'] not in {'PASS', 'FAIL', 'NOT_RUN', 'LIMITED'}):
        raise ValueError('invalid result schema')
    if type(row.get('id')) is not str or row['id'] not in SCENARIOS:
        raise ValueError('unknown controlled scenario')
    for key in ('attempts', 'failures', 'errors', 'timeouts'):
        if type(row.get(key)) is not int or row[key] < 0:
            raise ValueError('explicit nonnegative integer counts required')
    if sum(row[k] for k in ('failures', 'errors', 'timeouts')) > row['attempts']:
        raise ValueError('outcome counts exceed all attempts (disjoint outcomes)')
    if type(row.get('requires_acoustic')) is not bool:
        raise ValueError('acoustic classification must be strict bool')
    if row['requires_acoustic'] is not SCENARIOS[row['id']]:
        raise ValueError('report cannot override controlled acoustic policy')
    if row['status'] == 'PASS':
        if row['attempts'] == 0 or any(row[k] for k in ('failures', 'errors', 'timeouts')):
            raise ValueError('PASS requires positive attempts and no bad outcomes')
        if row.get('scope') != 'product':
            raise ValueError('fixture results cannot be product PASS')
        if row['requires_acoustic'] and not row.get('acoustic_observation'):
            raise ValueError('missing independent acoustic observation')
    elif row['status'] == 'NOT_RUN' and row['attempts'] != 0:
        raise ValueError('NOT_RUN cannot claim attempts')


def validate_product_result(row):
    validate_report_schema(row)
    if row['status'] == 'PASS':
        # No real product adapter, trusted execution receipt or independent
        # product oracle has been implemented/approved in M02. Fail closed.
        # Strings, hashes and even structurally valid fabricated rows cannot
        # substitute for that missing binding. Do not add a bypass argument.
        raise ValueError('product PASS disabled: no approved product execution binding')


def execute(adapter, case, oracle='fixture.stop.v1'):
    """Fixture-only executor with a fixed schema/oracle; no callable oracle bypass.

    It returns an observation, never a product receipt or PASS report.
    """
    if type(case) is not dict or case != {'scenario': 'fixture.stop.v1'}:
        raise ValueError('unregistered fixture case')
    if type(oracle) is not str or oracle != 'fixture.stop.v1':
        raise ValueError('unregistered oracle; callable oracles are not accepted')
    if adapter is None or not callable(adapter):
        raise ValueError('no product adapter')
    observed = adapter(case)  # exceptions deliberately propagate
    if type(observed) is not dict or set(observed) != {'muted'} or type(observed['muted']) is not bool:
        raise ValueError('observation must match the nonempty stop schema')
    if observed['muted'] is not True:
        raise AssertionError('product observation violates assertion')
    return observed
