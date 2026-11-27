#!/usr/bin/env python3
"""Trusted local release closure. Never derives source membership from an APK's own inventory."""
import hashlib,json,re,struct,subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCE_DIRS=('app/src/main','app/src/debug','app/src/v2Debug','app/libs','assets/v2-default')
PUBLIC_TRANSPORT={
 'app/src/v2Debug/assets/v2-transport/ca.pem':'ef47caf47e3d66b428d51a8d15c0c5960646af540c294caed37f7fcde3febe98',
 'app/src/v2Debug/assets/v2-transport/ssh.properties':'df09fed1f81baf30cb6abfa6a5edc32461d692b53f852e065f78ec35107aa1b2'}
def require(condition,reason):
 if not condition:raise AssertionError(reason)
EXACT_FILES={'app/build.gradle.kts','app/v2-release.json','settings.gradle.kts','gradle.properties','gradlew',
             'scripts/v2-build-metadata.py','scripts/v2-release-snapshot.py','scripts/v2-native-audit.py'}
def selected(path):
 return path.startswith(('app/src/main/','app/src/debug/','app/src/v2Debug/','app/libs/','gradle/wrapper/','assets/v2-default/')) or path in EXACT_FILES
def source_inventory(root):
 root=Path(root).resolve()
 tracked=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
 paths=sorted(p for p in tracked if p and selected(p))
 inventory={}
 for path in paths:
  candidate=Path(path);file=root/candidate
  require(not candidate.is_absolute() and '..' not in candidate.parts,'source_path')
  require(not file.is_symlink() and file.is_file() and file.resolve().is_relative_to(root),'source_file')
  require(all(not parent.is_symlink() for parent in file.parents if parent!=root),'source_symlink')
  if path not in PUBLIC_TRANSPORT:require(file.suffix not in {'.pem','.key','.jks','.keystore'},'private_source_file')
  require(file.suffix!='.properties' or path in {'gradle.properties','gradle/wrapper/gradle-wrapper.properties'} or path in PUBLIC_TRANSPORT,'private_properties')
  raw=file.read_bytes();digest=hashlib.sha256(raw).hexdigest()
  if path in PUBLIC_TRANSPORT:require(digest==PUBLIC_TRANSPORT[path],'public_transport_pin')
  inventory[path]={'sha256':digest,'size':len(raw)}
 for path in EXACT_FILES:
  file=root/path
  if file.exists() or file.is_symlink():require(path in inventory,'uninventoried_source')
 # Complete physical selected closure, including untracked, ignored and symlink entries.
 for directory in (*SOURCE_DIRS,'gradle/wrapper'):
  require(not (root/directory).is_symlink(),'source_symlink')
  for file in (root/directory).rglob('*'):
   require(not file.is_symlink(),'source_symlink')
   if file.is_file():require(file.relative_to(root).as_posix() in inventory,'uninventoried_source')
 return inventory

def canonical(inventory):return json.dumps(inventory,sort_keys=True,separators=(',',':')).encode()
def resource_files(root):
 root=Path(root).resolve();assets=root/'assets/v2-default'
 raw=(assets/'manifest.json').read_bytes();rows=json.loads(raw)
 require(isinstance(rows,list) and len(rows)==60,'resource_count')
 ids=set();pngs={};sources=set()
 for row in rows:
  require(isinstance(row,dict),'resource_row')
  id=row.get('id');require(isinstance(id,str) and re.fullmatch('[a-z0-9-]{1,64}',id) and id not in ids,'resource_id');ids.add(id)
  png=f'png/{id}.png';source=f'source/{id}.svg'
  require(row.get('png')==png and row.get('source')==source,'resource_path')
  require(type(row.get('width')) is int and type(row.get('height')) is int and row['width']==row['height']==512,'resource_declared_dimensions')
  for name,key in [(source,'source_sha256'),(png,'png_sha256')]:
   file=assets/name
   require(file.is_file() and not file.is_symlink() and file.resolve().is_relative_to(assets),'resource_file')
   data=file.read_bytes();digest=row.get(key)
   require(isinstance(digest,str) and re.fullmatch('[a-f0-9]{64}',digest) and hashlib.sha256(data).hexdigest()==digest,'resource_payload_hash')
   if name==png:
    require(33<=len(data)<=1_048_576 and data[:16]==b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR','resource_png_header')
    require(struct.unpack('>II',data[16:24])==(512,512),'resource_png_dimensions')
    pngs['assets/v2-default/'+png]=data
   else:
    require(0<len(data)<=1_048_576,'resource_svg_size')
    svg=ET.fromstring(data)
    require(svg.tag=='{http://www.w3.org/2000/svg}svg' and svg.get('width')=='512' and svg.get('height')=='512' and
            svg.get('viewBox','').split()==['0','0','512','512'],'resource_svg_dimensions')
    sources.add(source)
 for folder,expected in [('png',{p.removeprefix('assets/v2-default/') for p in pngs}),('source',sources)]:
  actual=set()
  for file in (assets/folder).rglob('*'):
   require(not file.is_symlink(),'resource_symlink')
   if file.is_file():actual.add(file.relative_to(assets).as_posix())
  require(actual==expected,'resource_file_set')
 return raw,pngs

def bind_resources(inventory,manifest,pngs):
 """Keep validated resource bytes coherent with the separately collected source receipts."""
 for path,data in {'assets/v2-default/manifest.json':manifest,**pngs}.items():
  require(inventory.get(path)=={'sha256':hashlib.sha256(data).hexdigest(),'size':len(data)},'resource_snapshot_changed')
 for row in json.loads(manifest):
  require(inventory.get('assets/v2-default/'+row['source'],{}).get('sha256')==row['source_sha256'],'resource_snapshot_changed')
