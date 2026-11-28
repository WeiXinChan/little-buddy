#!/usr/bin/env python3
"""Immutable original-source negative controls; synthetic local protocol only."""
import hashlib,io,json,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests.v2.test_superseded_output import SupersededOutput
SOURCE='12c054b770632810a27051e0bcae127f21c59229'
raw=subprocess.check_output(['git','show',SOURCE+':backend/v2/voice.py'],cwd=ROOT)
namespace={'__name__':'v2_immutable_negative_control'}
exec(compile(raw,'v2_immutable_negative_control','exec'),namespace)
names=['test_old_tts_timeout_cannot_fail_new_revision','test_old_output_deadline_cannot_expire_fresh_input']
tests=[SupersededOutput(name) for name in names]
for test in tests:test.peer_type=namespace['VoicePeer']
result=unittest.TextTestRunner(stream=io.StringIO()).run(unittest.TestSuite(tests))
assert len(result.failures)==2 and not result.errors,'negative_control_not_reproduced'
print(json.dumps(dict(source=SOURCE,source_file_sha256=hashlib.sha256(raw).hexdigest(),
    tests=2,expected_failures=2,errors=0,cloud_calls=0,negative_control='REPRODUCED',
    terminal_codes=[[e.get('code') for e in test.wire.events if e['type']=='failure'] for test in tests])))
