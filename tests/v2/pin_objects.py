"""Historical source identity is immutable; execution still verifies local bytes."""
import hashlib,io,json,subprocess,tarfile,tempfile
from pathlib import Path
from unittest.mock import patch

def assert_git_pin(test,module,pin_name):
    scripts=Path(module.__file__).resolve().parent;root=scripts.parent
    pin=json.loads((scripts/pin_name).read_text());test.assertEqual(pin['source'],module.SOURCE)
    raw=subprocess.check_output(['git','archive','--format=tar',pin['source'],'--',*pin['files']],cwd=root)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for name,expected in pin['files'].items():
            test.assertEqual(hashlib.sha256(archive.extractfile(name).read()).hexdigest(),expected,name)

def assert_rejects_changed_copy(test,module,pin_name):
    scripts=Path(module.__file__).resolve().parent;root=scripts.parent
    pin=json.loads((scripts/pin_name).read_text());name='backend/v2/voice.py'
    # A minimal temporary manifest exercises the real unchanged admission port.
    with tempfile.TemporaryDirectory() as temporary:
        folder=Path(temporary);(folder/'scripts').mkdir();target=folder/name;target.parent.mkdir(parents=True)
        expected=subprocess.check_output(['git','show',module.SOURCE+':'+name],cwd=root)
        target.write_bytes(expected)
        (folder/'scripts'/pin_name).write_text(json.dumps(dict(source=module.SOURCE,files={name:pin['files'][name]})))
        with patch.object(module,'ROOT',folder/'scripts'):
            test.assertEqual(len(module.verify_source()),64)
            target.write_bytes(expected+b'\n# synthetic source mismatch\n')
            with test.assertRaisesRegex(ValueError,'source_bytes'):module.verify_source()
