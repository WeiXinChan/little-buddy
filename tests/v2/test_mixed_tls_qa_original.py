"""Literal original QA inputs/assertions preserved; not used as the new positive."""
import copy,importlib.util,json
from pathlib import Path
from scripts.v2_mixed_tls import Plan
ROOT=Path(__file__).resolve().parents[2]/'docs/testing/v2/mixed-tls/association-fix'
spec=importlib.util.spec_from_file_location('original_pr116_qa',ROOT/'independent-original.py')
qa=importlib.util.module_from_spec(spec);spec.loader.exec_module(qa)
qa.fixture=lambda:(Plan(duration=90),copy.deepcopy(json.loads((ROOT/'original-fixture.json').read_bytes())))
Independent=qa.Independent
