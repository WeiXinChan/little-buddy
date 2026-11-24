import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reuse_b2_apks import host_only,verified_copy
class ReuseTests(unittest.TestCase):
 def test_all_non_host_build_inputs_are_rejected(self):
  self.assertTrue(host_only(['scripts/m06/x.py','.github/workflows/v2-eyes.yml','docs/testing/v2/r100/ci24/x.md']))
  for path in ['settings.gradle.kts','gradle.properties','gradle/wrapper/gradle-wrapper.jar','app/src/main/a.kt','app/src/androidTest/a.kt','gradle/verification-metadata.xml','build.gradle.kts']:
   self.assertFalse(host_only(['scripts/m06/x.py',path]))
 def test_both_hashes_verified_before_copy_and_corrupt_pair_refused(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);src=root/'src';src.mkdir();dst=root/'dst'
   (src/'a.apk').write_bytes(b'a');(src/'b.apk').write_bytes(b'b')
   spec={n:(hashlib.sha256(v).hexdigest(),str(dst/n)) for n,v in [('a.apk',b'a'),('b.apk',b'b')]}
   (src/'b.apk').write_bytes(b'bad')
   with self.assertRaises(ValueError):verified_copy(src,spec)
   self.assertFalse(dst.exists())
   (src/'b.apk').write_bytes(b'b');verified_copy(src,spec)
   self.assertEqual((dst/'a.apk').read_bytes(),b'a')
