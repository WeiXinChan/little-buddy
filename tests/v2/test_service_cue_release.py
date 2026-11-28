import hashlib,importlib.util,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('snapshot',ROOT/'scripts/v2-release-snapshot.py')
snapshot=importlib.util.module_from_spec(spec);spec.loader.exec_module(snapshot)
class ServiceCueRelease(unittest.TestCase):
    def test_exact_root_material_and_old_cue_unchanged(self):
        files=snapshot.service_failure_files(ROOT)
        self.assertEqual(164160,len(files['assets/v2-service-failure.pcm']))
        old=snapshot.clarification_files(ROOT)['assets/v2-local-clarify.pcm']
        self.assertEqual('b11fca1d95974735e3f48faf6e8d21d8b8a541c0bf7d4c521c5d10c3f8b260e7',hashlib.sha256(old).hexdigest())
    def test_changed_pcm_cannot_self_certify_with_recomputed_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'app/src/v2Debug/assets';path.mkdir(parents=True)
            pcm=bytes(164160);(path/'v2-service-failure.pcm').write_bytes(pcm)
            (path/'v2-service-failure.sha256').write_text(hashlib.sha256(pcm).hexdigest()+'\n')
            with self.assertRaisesRegex(AssertionError,'service_failure_reviewed_pcm'):snapshot.service_failure_files(folder)
