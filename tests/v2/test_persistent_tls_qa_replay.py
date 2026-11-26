"""QA test bodies unchanged, original pre-fix fixture loaded byte-for-byte."""
import copy,importlib.util,json
from pathlib import Path
BASE=Path(__file__).resolve().parents[2]/'docs/testing/v2/persistent-tls/qa-fix'
spec=importlib.util.spec_from_file_location('pr115_original',BASE/'independent-original.py')
qa=importlib.util.module_from_spec(spec);spec.loader.exec_module(qa)
qa.fixture=lambda:copy.deepcopy(json.loads((BASE/'original-fixture.json').read_bytes()))
Independent=qa.Independent
Release=qa.Release
