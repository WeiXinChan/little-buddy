"""Run fixture self-tests and generate explicitly untested product rows."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import unittest
from tools.v2_harness.evidence import provenance


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.discover('tools/v2_harness/tests')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {
        'scope': 'fixture-self-test-only', 'source': 'synthetic', 'provenance': provenance(),
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'python': platform.python_version(), 'host': platform.system(),
        'device': 'none', 'network': 'none', 'seed': 80,
        'attempts': result.testsRun, 'failures': len(result.failures),
        'errors': len(result.errors), 'skipped': len(result.skipped),
        'failure_cases': [t.id() for t, _ in result.failures + result.errors],
        'product_results': [{'id': f'A{i:02}', 'status': 'NOT_RUN', 'attempts': 0}
                            for i in range(1, 39)],
        'findings': {f'F{i:02}': 'OPEN_PENDING_IMPLEMENTATION_AND_INDEPENDENT_REVIEW'
                     for i in range(1, 6)},
        'limitations': ['No product adapter, device, speech recognizer, cloud or acoustic execution',
                        'No child voice evidence; no elapsed 7-day test'],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
