#!/usr/bin/env python3
"""Small offline release-guard fixtures, NOT installable APKs or PR109 QA evidence."""
import shutil,warnings,struct,hashlib,importlib.util,json,subprocess,tempfile,unittest,zipfile
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
   'scripts/v2-build-metadata.py':(ROOT/'scripts/v2-build-metadata.py').read_bytes(),
   'scripts/v2-release-snapshot.py':(ROOT/'scripts/v2-release-snapshot.py').read_bytes()}
  files['scripts/v2-native-audit.py']=(ROOT/'scripts/v2-native-audit.py').read_bytes()
  for path in (ROOT/'app/src/v2Debug/cpp').rglob('*'):
   if path.is_file():files[path.relative_to(ROOT).as_posix()]=path.read_bytes()
  files['app/src/v2Debug/jniLibs/arm64-v8a/libwali-v2-kws.so']=(ROOT/'app/src/v2Debug/jniLibs/arm64-v8a/libwali-v2-kws.so').read_bytes()
  for name in ['v2-local-clarify.pcm','v2-local-clarify.sha256','v2-service-failure.pcm','v2-service-failure.sha256']:
   files['app/src/v2Debug/assets/'+name]=(ROOT/'app/src/v2Debug/assets'/name).read_bytes()
  for name,data in files.items():
   p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
  shutil.copytree(ROOT/'assets/v2-default',self.root/'assets/v2-default',dirs_exist_ok=True)
  (self.root/'assets/v2-default/manifest.json').write_bytes(self.resource)
  subprocess.run(['git','add','.'],cwd=self.root,check=True)
  self.output=self.root/'generated'
 def generate(self,private=False,diagnostics=False,configuration_only=False):
  with patch.object(gen,'ROOT',self.root):return gen.generate(self.output,diagnostics,private,configuration_only)
 def inspect(self,metadata=None,inventory=None,resource=None,images=None,duplicate=None,private=False,diagnostics=False,payload=False,configuration_only=False,native_missing=False,native_extra=False,native_payload=None,clip_missing=False,clip_extra=False,clip_payload=None,service_missing=False,service_extra=False,service_payload=None):
  meta=self.generate(private,diagnostics) if metadata is None else metadata
  raw=(self.output/'v2-source-inventory.json').read_bytes() if inventory is None else inventory
  archive=self.root/'NOT_AN_INSTALLABLE_APK.zip'
  with zipfile.ZipFile(archive,'w') as z:
   for name,data in gen._snapshot.clarification_files(self.root).items():
    if not clip_missing:z.writestr(name,clip_payload if name.endswith('.pcm') and clip_payload is not None else data)
   for name,data in gen._snapshot.service_failure_files(self.root).items():
    if not service_missing:z.writestr(name,service_payload if name.endswith('.pcm') and service_payload is not None else data)
   if service_extra:z.writestr('assets/v2-service-failure-extra.pcm',b'WRONG EXTRA AUDIO')
   if clip_extra:z.writestr('assets/v2-local-clarify-extra.pcm',b'WRONG EXTRA AUDIO')
   if payload:z.writestr('assets/v2-device-preset.bin',b'SYNTHETIC PRIVATE BUILD FIXTURE ONLY')
   if not native_missing:z.writestr('lib/arm64-v8a/libwali-v2-kws.so',(self.root/'app/src/v2Debug/jniLibs/arm64-v8a/libwali-v2-kws.so').read_bytes() if native_payload is None else native_payload)
   if native_extra:z.writestr('lib/x86_64/libwali-v2-kws.so',b'WRONG ABI FIXTURE')
   z.writestr('assets/v2-build.json',json.dumps(meta));z.writestr('assets/v2-source-inventory.json',raw)
   z.writestr('assets/v2-default/manifest.json',self.resource if resource is None else resource)
   pngs=self.pngs() if images is None else images
   for name,payload in pngs.items():z.writestr(name,payload)
   if duplicate:
    with warnings.catch_warnings():
     warnings.simplefilter('ignore',UserWarning);z.writestr(duplicate,b'DUPLICATE UNIT FIXTURE')
  with patch.object(verify,'__file__',str(self.root/'scripts/verify-v2-release.py')):return verify.inspect(archive,diagnostics,private,configuration_only)
 def test_service_failure_apk_missing_extra_changed_or_duplicate_rejected(self):
  for kwargs in [dict(service_missing=True),dict(service_extra=True)]:
   with self.assertRaisesRegex(ValueError,'service_failure_asset_set'):self.inspect(**kwargs)
  with self.assertRaisesRegex(ValueError,'service_failure_asset_bytes'):self.inspect(service_payload=b'CHANGED FIXTURE')
  with self.assertRaisesRegex(ValueError,'duplicate'):self.inspect(duplicate='assets/v2-service-failure.pcm')
 def test_fixed_clarification_apk_missing_extra_or_changed_is_rejected(self):
  for kwargs in [dict(clip_missing=True),dict(clip_extra=True)]:
   with self.assertRaisesRegex(ValueError,'clarification_asset_set'):self.inspect(**kwargs)
  with self.assertRaisesRegex(ValueError,'clarification_asset_bytes'):self.inspect(clip_payload=b'CHANGED FIXTURE')
 def test_fixed_clarification_missing_bad_hash_or_unbounded_cannot_build(self):
  pcm=self.root/'app/src/v2Debug/assets/v2-local-clarify.pcm';receipt=pcm.with_suffix('.sha256')
  original=pcm.read_bytes();original_hash=receipt.read_bytes()
  pcm.unlink()
  with self.assertRaises(FileNotFoundError):self.generate()
  pcm.write_bytes(original)
  receipt.write_bytes(b'0'*64+b'\n')
  with self.assertRaisesRegex(AssertionError,'clarification_hash'):self.generate()
  receipt.write_bytes(original_hash);pcm.write_bytes(b'0'*288002)
  with self.assertRaisesRegex(AssertionError,'clarification_pcm_bounds'):self.generate()
 def test_native_source_change_cannot_reuse_prebuilt_receipt(self):
  path=self.root/'app/src/v2Debug/cpp/v2_kws.cc';path.write_bytes(path.read_bytes()+b'// stale binary negative\n')
  with self.assertRaisesRegex(ValueError,'native_source_binding'):self.generate()
 def test_native_bad_abi_even_with_updated_library_hash(self):
  path=self.root/'app/src/v2Debug/jniLibs/arm64-v8a/libwali-v2-kws.so';raw=bytearray(path.read_bytes());raw[18:20]=(62).to_bytes(2,'little');path.write_bytes(raw)
  lock=self.root/'app/src/v2Debug/cpp/native-lock.json';data=json.loads(lock.read_text());data['library_sha256']=hashlib.sha256(raw).hexdigest();lock.write_text(json.dumps(data))
  with self.assertRaisesRegex(ValueError,'native_elf_arm64'):self.generate()
 def test_native_missing_extra_and_wrong_apk_bytes(self):
  with self.assertRaisesRegex(ValueError,'native_apk_set'):self.inspect(native_missing=True)
  with self.assertRaisesRegex(ValueError,'native_apk_set'):self.inspect(native_extra=True)
  with self.assertRaisesRegex(ValueError,'native_apk_bytes'):self.inspect(native_payload=b'WRONG BINARY FIXTURE')
 def test_strict_rc9_identity_with_corrected_resources(self):
  meta=self.inspect();self.assertEqual((37,'2.0.0-rc9.nopin.startup2','com.littlebuddy.sim.v2'),(meta['version_code'],meta['version_name'],meta['application_id']))
  self.assertTrue(meta['build_id'].startswith('v2-37-'));self.assertEqual(gen.RC9_RESOURCES_MANIFEST,meta['resources_manifest_sha256'])
 def test_generator_refuses_old_or_mislabeled_identity(self):
  p=self.root/'app/v2-release.json';original=json.loads(p.read_text())
  for code,name in [(22,'2.0.0-rc8'),(23,'2.0.0-rc8'),(30,'2.0.0-rc10'),(35,'2.0.0-rc9.nopin.recovery1'),(36,'2.0.0-rc9.nopin.startup1')]:
   p.write_text(json.dumps(dict(original,version_code=code,version_name=name)))
   with self.assertRaises(AssertionError):self.generate()
 def test_generator_refuses_old_library_even_with_rc9_version(self):
  (self.root/'assets/v2-default/manifest.json').write_bytes(self.old_resource)
  with self.assertRaises(AssertionError):self.generate()
 def test_inspector_refuses_old_or_mislabeled_identity(self):
  meta=self.generate()
  for code,name in [(22,'2.0.0-rc8'),(23,'2.0.0-rc8'),(30,'2.0.0-rc10'),(35,'2.0.0-rc9.nopin.recovery1'),(36,'2.0.0-rc9.nopin.startup1')]:
   with self.assertRaisesRegex(ValueError,'candidate_version_mismatch'):self.inspect(dict(meta,version_code=code,version_name=name))
 def test_inspector_refuses_old_images_relabelled_rc9(self):
  meta=self.generate();old=self.old_resource;(self.root/'assets/v2-default/manifest.json').write_bytes(old)
  # Negative fixture only: coherent receipts cannot override the independent RC9 resource pin.
  raw=gen._snapshot.canonical(gen.source_inventory(self.root));digest=hashlib.sha256(raw).hexdigest()
  meta.update(resources_manifest_sha256=hashlib.sha256(old).hexdigest(),source_content_sha256=digest,build_id='v2-37-'+digest[:16])
  with self.assertRaisesRegex(ValueError,'candidate_resources_mismatch'):self.inspect(meta,inventory=raw,resource=old)
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
 def pngs(self):return {'assets/v2-default/png/'+p.name:p.read_bytes() for p in (self.root/'assets/v2-default/png').glob('*.png')}
 def test_strict_inventory_receipt_size_fields_and_build_id(self):
  meta=self.generate();original=json.loads((self.output/'v2-source-inventory.json').read_bytes())
  for mutation in ['size','extra_key','bool_size']:
   inventory=json.loads(json.dumps(original));receipt=inventory['app/src/main/Sentinel.kt']
   if mutation=='size':receipt['size']+=1
   elif mutation=='extra_key':receipt['trusted']=True
   else:receipt['size']=True
   raw=gen._snapshot.canonical(inventory);digest=hashlib.sha256(raw).hexdigest()
   changed=dict(meta,source_content_sha256=digest,build_id='v2-37-'+digest[:16])
   with self.assertRaises(ValueError):self.inspect(changed,inventory=raw)
  with self.assertRaisesRegex(ValueError,'source_build_id_mismatch'):self.inspect(dict(meta,build_id='v2-37-'+('0'*16)))
 def test_inspector_rejects_added_tracked_selected_source(self):
  meta=self.generate();(self.root/'app/src/main/Added.kt').write_text('// ADDED\n')
  subprocess.run(['git','add','app/src/main/Added.kt'],cwd=self.root,check=True)
  with self.assertRaises(ValueError):self.inspect(meta)
 def test_ignored_physical_selected_file_is_not_ignored_by_inspector(self):
  meta=self.generate();(self.root/'.git/info/exclude').write_text('/app/src/main/Hidden.kt\n')
  (self.root/'app/src/main/Hidden.kt').write_text('// HIDDEN\n')
  with self.assertRaises(ValueError):self.inspect(meta)
 def test_generator_rejects_wrong_staged_png_and_svg(self):
  for relative in ['png/star-bunny.png','source/star-bunny.svg']:
   path=self.root/'assets/v2-default'/relative;original=path.read_bytes()
   try:
    path.write_bytes(original+b'CHANGED');subprocess.run(['git','add','assets'],cwd=self.root,check=True)
    with self.assertRaisesRegex(AssertionError,'resource_payload_hash'):self.generate()
   finally:path.write_bytes(original)
 def test_actual_png_svg_dimensions_even_with_updated_row_hash(self):
  manifest=self.root/'assets/v2-default/manifest.json';original=manifest.read_bytes()
  for folder,key in [('png','png_sha256'),('source','source_sha256')]:
   path=self.root/'assets/v2-default'/folder/('star-bunny.png' if folder=='png' else 'star-bunny.svg');before=path.read_bytes()
   try:
    data=before[:16]+struct.pack('>I',513)+before[20:] if folder=='png' else before.replace(b'width="512"',b'width="513"',1)
    path.write_bytes(data);rows=json.loads(original);next(r for r in rows if r['id']=='star-bunny')[key]=hashlib.sha256(data).hexdigest()
    manifest.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    with self.assertRaisesRegex(AssertionError,'resource_'+('svg' if folder=='source' else folder)+'_dimensions'):gen._snapshot.resource_files(self.root)
   finally:path.write_bytes(before);manifest.write_bytes(original)
 def test_apk_exact_png_bytes_and_set_and_duplicate_entries(self):
  meta=self.generate();pngs=self.pngs();star='assets/v2-default/png/star-bunny.png';cat='assets/v2-default/png/cat.png'
  self.assertNotEqual(pngs[star],pngs[cat])
  missing=dict(pngs);del missing[star]
  extra=dict(pngs);extra['assets/v2-default/png/extra.png']=pngs[cat]
  changed=dict(pngs);changed[star]=pngs[cat]
  for images in [missing,extra,changed]:
   with self.assertRaises(ValueError):self.inspect(meta,images=images)
  for duplicate in [star,'assets/v2-default/manifest.json','assets/v2-build.json']:
   with self.assertRaisesRegex(ValueError,'duplicate_zip_entry'):self.inspect(meta,duplicate=duplicate)
 def test_missing_extra_local_resources_and_metadata_origin(self):
  meta=self.generate();extra=self.root/'assets/v2-default/png/extra.png';extra.write_bytes(b'EXTRA')
  try:
   with self.assertRaises(AssertionError):self.generate()
  finally:extra.unlink()
  star=self.root/'assets/v2-default/png/star-bunny.png';data=star.read_bytes();star.unlink()
  try:
   with self.assertRaises(AssertionError):self.generate()
  finally:star.write_bytes(data)
  with self.assertRaisesRegex(ValueError,'candidate_config_mismatch'):self.inspect(dict(meta,source_base='f'*40))
 def test_configuration_only_requires_private_diagnostic_admission(self):
  for private,diagnostics in [(False,False),(True,False),(False,True)]:
   with self.assertRaisesRegex(AssertionError,'configuration_only_requires_private_diagnostics'):
    self.generate(private,diagnostics,True)
  meta=self.generate(True,True,True)
  with self.assertRaisesRegex(ValueError,'configuration_diagnostic_mode_mismatch'):
   self.inspect(meta,private=True,diagnostics=True,payload=True)
  checked=self.inspect(meta,private=True,diagnostics=True,payload=True,configuration_only=True)
  self.assertTrue(checked['configuration_diagnostic_only'])
 def test_private_candidate_requires_explicit_mode_and_has_rc9_identity(self):
  meta=self.generate(private=True,diagnostics=True)
  self.assertEqual((37,'2.0.0-rc9.nopin.startup2.integrated1.device1'),(meta['version_code'],meta['version_name']))
  self.assertEqual('private_registered_device',self.inspect(meta,private=True,diagnostics=True,payload=True)['distribution'])
  with self.assertRaisesRegex(ValueError,'explicit_build_mode_mismatch'):self.inspect(meta,payload=True)
 def test_missing_or_unexpected_private_payload_refused(self):
  meta=self.generate(private=True)
  with self.assertRaisesRegex(ValueError,'explicit_build_mode_mismatch'):self.inspect(meta,private=True)
  public=self.generate()
  with self.assertRaisesRegex(ValueError,'explicit_build_mode_mismatch'):self.inspect(public,payload=True)
 def test_diagnostic_flag_does_not_resurrect_obsolete_rc8_packaging(self):
  meta=self.generate(diagnostics=True)
  self.assertEqual('2.0.0-rc9.nopin.startup2',meta['version_name'])
  self.assertTrue(self.inspect(meta,diagnostics=True)['diagnostics_enabled'])
  with self.assertRaisesRegex(ValueError,'explicit_build_mode_mismatch'):self.inspect(meta)
 def test_private_mode_cannot_bypass_exact_source_inventory(self):
  meta=self.generate(private=True);claimed=json.loads((self.output/'v2-source-inventory.json').read_bytes())
  del claimed['app/src/main/Sentinel.kt'];raw=gen._snapshot.canonical(claimed);digest=hashlib.sha256(raw).hexdigest()
  meta.update(source_content_sha256=digest,build_id='v2-37-'+digest[:16])
  with self.assertRaisesRegex(ValueError,'source_inventory_set_mismatch'):self.inspect(meta,inventory=raw,private=True,payload=True)
 def test_private_mode_cannot_bypass_png_set_or_identity(self):
  meta=self.generate(private=True);images=self.pngs();del images['assets/v2-default/png/star-bunny.png']
  with self.assertRaisesRegex(ValueError,'apk_resource_set_mismatch'):self.inspect(meta,images=images,private=True,payload=True)
  with self.assertRaisesRegex(ValueError,'candidate_version_mismatch'):self.inspect(dict(meta,version_code=23),private=True,payload=True)
 def test_distribution_and_mode_types_are_strict(self):
  meta=self.generate(private=True)
  with self.assertRaisesRegex(ValueError,'explicit_build_mode_mismatch'):self.inspect(dict(meta,distribution='internal_debug_candidate'),private=True,payload=True)
  with self.assertRaisesRegex(ValueError,'explicit_build_mode_mismatch'):self.inspect(dict(meta,private_device_preset=1),private=True,payload=True)
if __name__=='__main__':unittest.main(verbosity=2)
