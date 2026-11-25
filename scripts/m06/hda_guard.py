"""Single synthetic HDA backend experiment. No AVD launch/root/audio by this helper."""
import hashlib,json,os,re
from pathlib import Path

class HdaStop(RuntimeError):
 def __init__(self,reason):self.reason=reason;super().__init__(reason)

def file_record(path,keys=None,feature=False):
 row=dict(status='UNAVAILABLE')
 try:
  if not path.is_file() or path.stat().st_size>262144:raise HdaStop('FILE_MISSING_OR_BOUND')
  raw=path.read_bytes();row['sha256']=hashlib.sha256(raw).hexdigest();text=raw.decode('utf-8','strict')
  if feature:
   values=[]
   for line in text.splitlines():
    if line.lstrip().startswith(('#',';')):continue
    if re.match(r'\s*VirtioSndCard\b',line):
     match=re.fullmatch(r'\s*VirtioSndCard\s*=\s*(on|off)\s*(?:#.*)?',line)
     if not match:raise HdaStop('FEATURE_SCHEMA')
     values.append(match[1])
   if len(values)!=1:raise HdaStop('FEATURE_MISSING_OR_DUPLICATE')
   row.update(status='AVAILABLE',VirtioSndCard=values[0])
  else:
   fields={}
   for key in keys:
    matches=[m[1].strip() for line in text.splitlines() if (m:=re.fullmatch(re.escape(key)+r'\s*=\s*([A-Za-z0-9_.-]{1,64})\s*',line))]
    if len(matches)!=1:raise HdaStop('PROPERTY_MISSING_OR_DUPLICATE')
    fields[key]=matches[0]
   row.update(status='AVAILABLE',fields=fields)
 except (OSError,UnicodeError,HdaStop) as e:row['reason']=e.reason if isinstance(e,HdaStop) else 'FILE_UNAVAILABLE'
 return row

def sdk_support(root):
 image=root/'system-images/android-36/google_apis/x86_64'
 records=dict(emulator_properties=file_record(root/'emulator/source.properties',('Pkg.Revision','Pkg.BuildId')),
              emulator_features=file_record(root/'emulator/lib/advancedFeatures.ini',feature=True),
              image_properties=file_record(image/'source.properties',('AndroidVersion.ApiLevel','SystemImage.Abi','SystemImage.TagId')),
              image_features=file_record(image/'advancedFeatures.ini',feature=True))
 supported=all(r['status']=='AVAILABLE' for r in records.values())
 supported=supported and records['emulator_properties']['fields']=={'Pkg.Revision':'37.3.10','Pkg.BuildId':'16970787'} and records['image_properties']['fields']=={'AndroidVersion.ApiLevel':'36','SystemImage.Abi':'x86_64','SystemImage.TagId':'google_apis'}
 return dict(status='AVAILABLE' if supported else 'STOP',fixture='NOT_RUN',files=records,
             scope='actual installed file declarations only; actual soundhw and guest HDA are separate mandatory gates')

def require_qemu_hda(args):
 values=[];virtio_device=False
 args=iter(args)
 for value in args:
  if value=='-soundhw':values.append(next(args,''))
  elif value.startswith('-soundhw='):values.append(value.split('=',1)[1])
  elif value=='-device':
   device=next(args,'')
   if device.split(',',1)[0].startswith('virtio-snd'):virtio_device=True
  elif value.startswith('-device='):
   if value.split('=',1)[1].split(',',1)[0].startswith('virtio-snd'):virtio_device=True
 if len(values)!=1:raise HdaStop('SOUNDHW_MISSING_OR_DUPLICATE')
 if values[0]!='hda' or virtio_device:raise HdaStop('SOUNDHW_NOT_EXCLUSIVE_HDA')
 return 'hda'

def guest_hda(prepared):
 if prepared.get('status')!='AVAILABLE' or prepared.get('root_uid')!=0:raise HdaStop('ROOT_OR_NATIVE_IDENTITY_UNAVAILABLE')
 before=prepared.get('before',{})
 if before.get('status')!='AVAILABLE':raise HdaStop('GUEST_SNAPSHOT_UNAVAILABLE')
 alsa=before.get('alsa',{});drivers=before.get('drivers',{})
 if alsa.get('status')!='AVAILABLE' or drivers.get('status')!='AVAILABLE':raise HdaStop('GUEST_CARD_OR_DRIVER_UNAVAILABLE')
 cards=[]
 for line in alsa.get('fields',[]):
  m=re.match(r'\s*([0-9]{1,3})\s+\[[^\]\r\n]{1,80}\]:\s*(.{1,180})',line)
  if m:cards.append((int(m[1]),bool(re.match(r'HDA-Intel\b',m[2])) and not re.search('virtio',m[2],re.I)))
 if len(cards)!=1 or not cards[0][1]:raise HdaStop('GUEST_NOT_SINGLE_HDA_CARD')
 expected='card'+str(cards[0][0]);rows=drivers.get('fields',[])
 if len(rows)!=1 or rows[0].get('card')!=expected or rows[0].get('driver_path')!='/sys/bus/pci/drivers/snd_hda_intel':raise HdaStop('GUEST_HDA_DRIVER_MISMATCH')
 return dict(card_index=cards[0][0],card_type='HDA_INTEL',driver='snd_hda_intel',root_uid=0)


def runtime_gate(metadata,root,prepare,proof,directory=Path('render')):
 directory.mkdir(parents=True,exist_ok=True);row=sdk_support(root)
 try:
  if row['status']!='AVAILABLE':raise HdaStop('SDK_FEATURE_SUPPORT_UNAVAILABLE')
  owned=proof.verify()
  audio=owned.get('audio',{})
  if not audio or any(r.get('soundhw')!='hda' for r in audio.values()):raise HdaStop('OWNED_QEMU_HDA_UNPROVEN')
  native=prepare(metadata)  # existing single-root/id0 path, never an additional root
  row.update(host_soundhw='hda',guest=guest_hda(native),status='AVAILABLE',fixture='READY_FOR_ORIGINAL_GATES')
 except Exception as e:
  row.update(status='STOP',fixture='NOT_RUN',reason=e.reason if isinstance(e,HdaStop) else 'HDA_IDENTITY_UNAVAILABLE',error_class=type(e).__name__)
 (directory/'hda-runtime-gate.json').write_text(json.dumps(row,indent=2))
 return row


if __name__=='__main__':
 import sys
 root=Path(os.environ['ANDROID_HOME']);row=sdk_support(root)
 Path('render').mkdir(exist_ok=True);Path('render/hda-support.json').write_text(json.dumps(row,indent=2))
 sys.exit(0 if row['status']=='AVAILABLE' else 1)
