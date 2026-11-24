"""Module-only evidence; never enables the generic product PASS gate."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import types
import unittest

ORIGINAL = 'e44433665a9f547df5e7872ad8aa1d1a29199a74'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--original-negative', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.original_negative:
        module = types.ModuleType('backend.v2.session')
        sys.modules[module.__name__] = module
        source = subprocess.check_output(['git', 'show', ORIGINAL + ':backend/v2/session.py'], text=True)
        exec(compile(source, 'original-session.py', 'exec'), module.__dict__)
        spec = importlib.util.spec_from_file_location('r96_tests', 'tests/v2/test_r96.py')
        tests = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tests)
        names = ['test_r96_01_story_after_effective_audio_ack',
                 'test_r96_02_reserve_pending_and_atomic_rejection',
                 'test_r96_03_invalid_schema_preserves_entire_state']
        suite = unittest.TestSuite(tests.Review96Tests(n) for n in names)
    else:
        suite = unittest.defaultTestLoader.discover('tests/v2')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    paths = ['backend/v2/session.py', 'tests/v2/test_r96.py', 'tests/v2/test_session.py',
             'tools/v2_harness/session_adapter.py', 'tools/v2_harness/r96_regression.py']
    report = dict(scope='original-head-negative-control' if args.original_negative else 'module-level-synthetic',
                  tested_head=ORIGINAL if args.original_negative else subprocess.check_output(
                      ['git', 'rev-parse', 'HEAD'], text=True).strip(),
                  dirty=bool(subprocess.check_output(['git','status','--porcelain'],text=True)),
                  attempts=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                  timeout_measurement='not instrumented; synchronous local suite',
                  failing_tests=[t.id() for t,_ in result.failures + result.errors],
                  product_pass_enabled=False,
                  sha256={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths})
    ok = (result.testsRun == 3 and len(result.failures) == 3 and not result.errors
          if args.original_negative else result.wasSuccessful())
    report['expected_outcome_observed'] = ok
    args.out.write_text(json.dumps(report,indent=2)+'\n')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
