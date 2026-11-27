"""Historical source identity is immutable; execution still verifies local bytes."""
import hashlib,io,json,subprocess,tarfile,tempfile
from pathlib import Path
from unittest.mock import patch

def assert_git_pin(test,module,pin_name):
    scripts=Path(module.__file__).resolve().parent;root=scripts.parent
    pin=json.loads((scripts/pin_name).read_text());test.assertEqual(pin['source'],module.SOURCE)
    origins=pin.get('file_sources',{name:pin['source'] for name in pin['files']})
    test.assertEqual(set(origins),set(pin['files']))
    groups={}
    for name,source in origins.items():
        test.assertIsInstance(source,str);test.assertRegex(source,r'^[0-9a-f]{40}$')
        groups.setdefault(source,[]).append(name)
    for source,names in groups.items():
        raw=subprocess.check_output(['git','archive','--format=tar',source,'--',*names],cwd=root)
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            for name in names:
                test.assertEqual(hashlib.sha256(archive.extractfile(name).read()).hexdigest(),pin['files'][name],name)

def assert_rejects_changed_copy(test,module,pin_name,name='backend/v2/voice.py'):
    scripts=Path(module.__file__).resolve().parent;root=scripts.parent
    pin=json.loads((scripts/pin_name).read_text())
    # A minimal temporary manifest exercises the real unchanged admission port.
    with tempfile.TemporaryDirectory() as temporary:
        folder=Path(temporary);(folder/'scripts').mkdir();target=folder/name;target.parent.mkdir(parents=True,exist_ok=True)
        source=pin.get('file_sources',{}).get(name,module.SOURCE)
        expected=subprocess.check_output(['git','show',source+':'+name],cwd=root)
        target.write_bytes(expected)
        (folder/'scripts'/pin_name).write_text(json.dumps(dict(source=module.SOURCE,files={name:pin['files'][name]})))
        verify=getattr(module,'verify_source',None) or module.verify
        admitted_root=folder/'scripts' if module.ROOT==scripts else folder
        with patch.object(module,'ROOT',admitted_root):
            result=verify()
            if result is not None:test.assertEqual(len(result),64)
            target.write_bytes(expected+b'\n# synthetic source mismatch\n')
            with test.assertRaisesRegex(ValueError,'source_bytes'):verify()
