"""QA test bodies/negative inputs unchanged; immutable old seeds bypass new happy fixture."""
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]/'docs/testing/v2/tls-retention/tls14-fix'
spec=importlib.util.spec_from_file_location('_qa_tls14_original',ROOT/'independent-original.py')
qa=importlib.util.module_from_spec(spec);spec.loader.exec_module(qa)
class IndependentReplay(qa.Independent):
    @classmethod
    def setUpClass(cls):
        # Only setup changes: capture-on-current-happy-fixture would change the
        # old RSS-only negative input. Preserve those exact pre-fix seeds instead.
        cls.examples=[(row['result'],row['arm'],row['nonce'],row['report_utf8'].encode()) for row in json.loads((ROOT/'original-seeds.json').read_text())]
