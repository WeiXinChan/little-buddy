#!/usr/bin/env python3
"""Small offline release-guard fixtures, NOT installable APKs or PR109 QA evidence."""
import hashlib,importlib.util,json,subprocess,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
gen=module('rc9metadata',ROOT/'scripts/v2-build-metadata.py')
verify=module('rc9verify',ROOT/'scripts/verify-v2-release.py')
class RC9Preparation(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  # Reconstruct only known manifest metadata, so a clean CI checkout needs no unmerged git object.
  # No corrected PNG is imported, and this unit fixture is not PR109 QA or a candidate APK.
  rows=json.loads((ROOT/'assets/v2-default/manifest.json').read_text())
  star=next(row for row in rows if row['id']=='star-bunny')
  star.update(source_sha256='2afb743809a1b3d17c1ac4176129538c4cf524655ceb85593a5cf497aead5d82',
   png_sha256='fda6219857f71782df6f6be1dc7d0944128766be0702b50b810672a0f27b8a03',
   visual_note='奶油长耳兔蓝围巾金星胸针；明确为幻想')
  cls.old_resource=(json.dumps(rows,ensure_ascii=False,indent=2)+'\n').encode()
  assert hashlib.sha256(cls.old_resource).hexdigest()=='16ec66f3cca282e4070481d803eb8a833f31ee6a1a7733f48bb0948329f1826e'
  star.update(source_sha256='0ef72c3ac222258a3b10f70cd273511df4897062277fef1e10af52274606b961',
   png_sha256='4076745a4988a76252df6e05ea42a43e0e62d5f74f7000a0700393d0b8f5082a',
   visual_note='奶油长耳兔、蓝围巾上的小金星胸针；胸针不遮口鼻，明确为幻想；本次位置修正待独立复核')
  cls.resource=(json.dumps(rows,ensure_ascii=False,indent=2)+'\n').encode()
  assert hashlib.sha256(cls.resource).hexdigest()==gen.RC9_RESOURCES_MANIFEST==verify.RC9_RESOURCES_MANIFEST
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=ROOT,prefix='rc9-guard-fixture-');self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name);subprocess.run(['git','init','-q',str(self.root)],check=True)
  files={'app/v2-release.json':(ROOT/'app/v2-release.json').read_bytes(),
   'assets/v2-default/manifest.json':self.resource,'app/src/main/Sentinel.kt':b'// OFFLINE UNIT FIXTURE ONLY\n',
   'scripts/v2-build-metadata.py':(ROOT/'scripts/v2-build-metadata.py').read_bytes()}
  for name,data in files.items():
   p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
  subprocess.run(['git','add','.'],cwd=self.root,check=True)
  self.output=self.root/'generated'
 def generate(self):
  with patch.object(gen,'ROOT',self.root):return gen.generate(self.output)
 def inspect(self,metadata=None,inventory=None,resource=None):
  meta=self.generate() if metadata is None else metadata
  raw=(self.output/'v2-source-inventory.json').read_bytes() if inventory is None else inventory
  archive=self.root/'NOT_AN_INSTALLABLE_APK.zip'
  with zipfile.ZipFile(archive,'w') as z:
   z.writestr('assets/v2-build.json',json.dumps(meta));z.writestr('assets/v2-source-inventory.json',raw)
   z.writestr('assets/v2-default/manifest.json',self.resource if resource is None else resource)
  with patch.object(verify,'__file__',str(self.root/'scripts/verify-v2-release.py')):return verify.inspect(archive)
 def test_strict_rc9_identity_with_corrected_resources(self):
  meta=self.inspect();self.assertEqual((23,'2.0.0-rc9','com.littlebuddy.sim.v2'),(meta['version_code'],meta['version_name'],meta['application_id']))
  self.assertTrue(meta['build_id'].startswith('v2-23-'));self.assertEqual(gen.RC9_RESOURCES_MANIFEST,meta['resources_manifest_sha256'])
 def test_generator_refuses_old_or_mislabeled_identity(self):
  p=self.root/'app/v2-release.json';original=json.loads(p.read_text())
  for code,name in [(22,'2.0.0-rc8'),(23,'2.0.0-rc8'),(24,'2.0.0-rc10')]:
   p.write_text(json.dumps(dict(original,version_code=code,version_name=name)))
   with self.assertRaises(AssertionError):self.generate()
 def test_generator_refuses_old_library_even_with_rc9_version(self):
  (self.root/'assets/v2-default/manifest.json').write_bytes(self.old_resource)
  with self.assertRaises(AssertionError):self.generate()
 def test_inspector_refuses_old_or_mislabeled_identity(self):
  meta=self.generate()
  for code,name in [(22,'2.0.0-rc8'),(23,'2.0.0-rc8'),(24,'2.0.0-rc10')]:
   with self.assertRaisesRegex(ValueError,'candidate_version_mismatch'):self.inspect(dict(meta,version_code=code,version_name=name))
 def test_inspector_refuses_old_images_relabelled_rc9(self):
  old=self.old_resource;(self.root/'assets/v2-default/manifest.json').write_bytes(old)
  # Build a self-consistent old-resource inventory to ensure the new resource pin itself rejects it.
  with patch.object(gen,'ROOT',self.root),patch.object(gen,'RC9_RESOURCES_MANIFEST',hashlib.sha256(old).hexdigest()):meta=gen.generate(self.output)
  with self.assertRaisesRegex(ValueError,'candidate_resources_mismatch'):self.inspect(meta,resource=old)
 def test_inventory_tampering_and_local_source_drift_still_rejected(self):
  meta=self.generate();raw=(self.output/'v2-source-inventory.json').read_bytes()
  with self.assertRaisesRegex(ValueError,'source_inventory_mismatch'):self.inspect(meta,inventory=raw+b' ')
  (self.root/'app/src/main/Sentinel.kt').write_text('// CHANGED\n')
  with self.assertRaisesRegex(ValueError,'source_snapshot_mismatch'):self.inspect(meta)
 def test_uninventoried_local_source_refused(self):
  (self.root/'app/src/main/Untracked.kt').write_text('// UNTRACKED\n')
  with self.assertRaises(AssertionError):self.generate()
 def test_backend_resource_mismatch_still_refused(self):
  meta=self.generate();old=hashlib.sha256(self.old_resource).hexdigest()
  backend={'format':1,'protocol_contract':verify.CONTRACT,'source_sha':'a'*40,'assets_manifest_sha256':old,
   'files':{'assets/v2-default/manifest.json':{'sha256':old}}}
  with self.assertRaisesRegex(ValueError,'release_resources_mismatch'):verify.compatible(meta,backend)
if __name__=='__main__':unittest.main(verbosity=2)
