"""Owned synthetic API36 only. Fixed read-only metadata; never PCM, full maps or log bodies."""
import json,os,re,time,threading
from pathlib import Path
from native_input_metadata import bounded,ALSA_COMMAND,alsa_fields
from sdk_gate_calibration import FINGERPRINT
from sdk_input_gate import PrivatePulse
ADB=['adb','-s','emulator-5554']
HAL='android.hardware.audio.service'
PS_COMMAND='set -o pipefail; ps -A -o PID,UID,NAME | awk \'$3 == "android.hardware.audio.service" {print $1, $2, $3}\''
EXE='/vendor/bin/hw/'+HAL
TAG='android.hardware.audio@7.1-impl.ranchu'
OBJECT=re.compile(r'/vendor/lib(?:64)?/(?:hw/(?:android\.hardware\.audio@7\.[01]-impl(?:\.ranchu)?|android\.hardware\.audio\.legacy@7\.1-impl\.ranchu|audio\.primary\.ranchu)|libtinyalsa)\.so')
MAPS_AWK=r'''awk '$NF ~ /^\/vendor\/lib(64)?\/(hw\/(android\.hardware\.audio@7\.[01]-impl(\.ranchu)?|android\.hardware\.audio\.legacy@7\.1-impl\.ranchu|audio\.primary\.ranchu)|libtinyalsa)\.so$/ {print $NF}' '''
DRIVERS=r'''for d in /sys/class/sound/card[0-9]*; do [ -e "$d" ] || continue; printf '%s ' "${d##*/}"; readlink -f "$d/device/driver"; done'''
EVENTS=('PCM_OPEN_NULL','PCM_OPEN_FAILED','PCM_PREPARE_FAILED','PCM_READ_FAILED','FALLBACK_TONE','LATE_SILENCE')
LOG_AWK=r'''awk -v lo=START -v hi=END '($1+0)>=lo && ($1+0)<=hi {e=""; if ($0 ~ /pcm_open returned nullptr/) e="PCM_OPEN_NULL"; else if ($0 ~ /pcm_open failed for nChannels=/) e="PCM_OPEN_FAILED"; else if ($0 ~ /pcm_prepare failed for nChannels=/) e="PCM_PREPARE_FAILED"; else if ($0 ~ /pcm_readi failed with/) e="PCM_READ_FAILED"; else if ($0 ~ /failed to create alsa source for/ && $0 ~ /creating a tone source instead/) e="FALLBACK_TONE"; else if ($0 ~ /pcm_readi was late delivering frames, inserting [0-9]+ us of silence/) e="LATE_SILENCE"; if (e!="") {printf "%s %s",$1,e; for(i=1;i<=NF;i++) if ($i ~ /^(nChannels|sampleRateHz|period_count|period_size|isOut)=[0-9]+[,;]?$/ || $i ~ /^\(-?[0-9]+\)$/) printf " %s",$i; if(e=="LATE_SILENCE") for(i=1;i<NF;i++) if($i ~ /^[0-9]+$/ && $(i+1)=="us") printf " silence_us=%s",$i; print ""}}' '''

class Unavailable(RuntimeError):
 def __init__(self,reason):self.reason=reason;super().__init__(reason)

def unavailable(reason):return dict(status='UNAVAILABLE',reason=reason)

def complete(meta):return meta.get('status')=='AVAILABLE' and meta.get('eof') is True and meta.get('capped') is False and type(meta.get('exit_code')) is int and meta['exit_code']==0

def allowed_objects(text):
 rows=text.splitlines()
 if len(rows)>128:raise Unavailable('MAP_ROW_LIMIT')
 if any(not OBJECT.fullmatch(r) for r in rows):raise Unavailable('OBJECT_PATH_NOT_ALLOWED')
 result=sorted(set(rows))
 if not result:raise Unavailable('NO_ALLOWED_MAPPED_OBJECT')
 if len(result)>8:raise Unavailable('OBJECT_COUNT_LIMIT')
 return result

def process_list(text):
 rows=[]
 for line in text.splitlines():
  m=re.fullmatch(r'\s*([1-9][0-9]{0,6})\s+(audioserver|[0-9]{1,6})\s+android\.hardware\.audio\.service\s*',line)
  if m:rows.append(dict(pid=int(m[1]),ps_uid=m[2]))
 if len(rows)!=1:raise Unavailable('HAL_PID_NOT_UNIQUE')
 return rows[0]

def identity(text,pid):
 lines=text.strip().splitlines()
 if len(lines)!=3:raise Unavailable('HAL_ID_SCHEMA')
 a=re.fullmatch(r'([0-9]+) ([0-9]+)',lines[0]);u=re.fullmatch(r'[0-9]{1,6}',lines[1])
 if not a or int(a[1])!=pid or not u or lines[2]!=EXE:raise Unavailable('HAL_ID_SCHEMA')
 return dict(pid=pid,starttime=int(a[2]),uid=int(lines[1]),exe=EXE)

def device_nodes(text):
 rows=[]
 for line in text.splitlines():
  m=re.fullmatch(r'c([rwx-]{9})\s+[0-9]+\s+([0-9]+)\s+([0-9]+)\s+([0-9]+),\s*([0-9]+)\s+.{1,40}\s+(controlC[0-9]+|pcmC[0-9]+D[0-9]+[cp]|hwC[0-9]+D[0-9]+|timer|seq)',line)
  if m:rows.append(dict(mode='c'+m[1],uid=int(m[2]),gid=int(m[3]),major=int(m[4]),minor=int(m[5]),node=m[6]))
 return rows[:32]

def drivers(text):
 rows=[]
 for line in text.splitlines():
  m=re.fullmatch(r'(card[0-9]+) (/sys/bus/(?:pci|platform|virtio)/drivers/[A-Za-z0-9_.-]{1,64})',line)
  if m:rows.append(dict(card=m[1],driver_path=m[2]))
 return rows[:16]

def mixer(text):
 rows=[]
 for line in text.splitlines():
  m=re.fullmatch(r'\s*([0-9]{1,5})\s+(INT|BOOL|ENUM)\s+([0-9]{1,3})\s+([A-Za-z0-9 _/-]{1,80}?)(?:\t| {2,})(.{1,120})\s*',line)
  if not m or not re.search(r'Capture|Mic|Input',m[4],re.I) or re.search(r'token|bearer|credential|header|key',m[4],re.I):continue
  v=m[5].strip();values=None
  if m[2]=='BOOL' and re.fullmatch(r'(?i)(?:on|off|true|false|0|1)(?: +(?:on|off|true|false|0|1)){0,7}',v):values=[x.lower() in ('on','true','1') for x in v.split()]
  elif re.fullmatch(r'-?[0-9]{1,10}(?:[ ,]+-?[0-9]{1,10}){0,7}',v):values=[int(n) for n in re.findall(r'-?[0-9]+',v)]
  elif v.lower() in ('on','off','true','false','mic','internal mic','external mic','front mic','line in','digital','analog','none'):values=[v.upper()]
  rows.append(dict(control=int(m[1]),type=m[2],count=int(m[3]),name=m[4].strip(),values=values,value_status='AVAILABLE' if values is not None else 'UNAVAILABLE'))
 return rows[:32]

def log_enums(text,start,end):
 counts={k:0 for k in EVENTS};events=[]
 for line in text.splitlines():
  parts=line.split()
  if len(parts)<2 or not re.fullmatch(r'[0-9]{9,12}(?:\.[0-9]{1,9})?',parts[0]) or parts[1] not in EVENTS:continue
  t=float(parts[0])
  if not start<=t<=end:continue
  numbers={}
  for part in parts[2:]:
   m=re.fullmatch(r'(nChannels|sampleRateHz|period_count|period_size|isOut|silence_us)=([0-9]{1,12})[,;]?',part)
   err=re.fullmatch(r'\((-?[0-9]{1,10})\)',part)
   if m:numbers[m[1]]=int(m[2])
   elif err:numbers['error_code']=int(err[1])
  counts[parts[1]]+=1
  if len(events)<64:events.append(dict(guest_epoch=t,event=parts[1],numbers=numbers))
 return dict(counts=counts,events=events,interpretation='only recognised existing tag/PID/time events; absent events do not prove no faults or enabled debug logging')

class NativeReadOnly:
 def __init__(self,directory=Path('render/native-input'),run=bounded,proof=None):
  self.directory=directory;directory.mkdir(parents=True,exist_ok=True);self.run=run;self.proof=proof;self.rooted=False;self.attempted=False;self.hal=None;self.objects=None;self.start=None;self.deadline=None
 def query(self,command,limit=16384,seconds=1):
  if self.deadline is not None:
   remaining=self.deadline-time.monotonic()
   if remaining<=0:raise Unavailable('SNAPSHOT_BUDGET')
   seconds=min(seconds,remaining)
  try:raw,meta=self.run(ADB+['shell',command],limit=limit,seconds=seconds)
  except Exception:raise Unavailable('COMMAND_EXCEPTION') from None
  if not complete(meta):raise Unavailable('COMMAND_UNAVAILABLE_OR_TRUNCATED')
  try:return raw.decode('utf-8','strict')
  except UnicodeDecodeError:raise Unavailable('INVALID_UTF8') from None
 def save(self,name,row):
  (self.directory/name).write_text(json.dumps(row,indent=2));return row
 def guard(self):
  pid=self.hal['pid'];cmd=f"awk '{{print $1, $22}}' /proc/{pid}/stat; awk '/^Uid:/{{print $2}}' /proc/{pid}/status; readlink /proc/{pid}/exe"
  value=identity(self.query(cmd,2048),pid)
  if self.hal.get('ps_uid')=='audioserver' and value['uid']!=1041:raise Unavailable('HAL_UID_CHANGED')
  if self.hal.get('ps_uid','').isdigit() and value['uid']!=int(self.hal['ps_uid']):raise Unavailable('HAL_UID_CHANGED')
  expected=self.hal.get('identity')
  if expected is not None and value!=expected:raise Unavailable('PID_REPLACED')
  return value
 def get_objects(self):
  return allowed_objects(self.query(MAPS_AWK+f'/proc/{self.hal["pid"]}/maps',8192))
 def object_info(self,path):
  # Only paths already matched exact OBJECT grammar reach a command.
  if not OBJECT.fullmatch(path):raise Unavailable('OBJECT_PATH_NOT_ALLOWED')
  result=dict(path=path,started_monotonic_ns=time.monotonic_ns())
  try:
   raw=self.query('sha256sum '+path,1024)
   m=re.fullmatch(r'([0-9a-f]{64})\s+'+re.escape(path)+r'\s*',raw)
   result['sha256']=m[1] if m else None;result['sha_status']='AVAILABLE' if m else 'UNAVAILABLE'
  except Unavailable as e:result['sha_status']='UNAVAILABLE';result['sha_reason']=e.reason
  try:
   raw=self.query("set -o pipefail; native_elf_reader=$(command -v readelf); case \"$native_elf_reader\" in /system/bin/readelf|/vendor/bin/readelf) \"$native_elf_reader\" -n "+path+" 2>/dev/null | awk '/Build ID:/{print $3}';; *) exit 4;; esac",2048)
   value=raw.strip();result['elf_build_id']=value if re.fullmatch('[0-9a-fA-F]{16,128}',value) else None
   result['build_id_status']='AVAILABLE' if result['elf_build_id'] else 'UNAVAILABLE'
  except Unavailable as e:result['build_id_status']='UNAVAILABLE';result['build_id_reason']=e.reason
  result['ended_monotonic_ns']=time.monotonic_ns()
  return result
 def prepare(self,metadata,*,metadata_proof=None):
  if self.attempted:return unavailable('ROOT_ALREADY_ATTEMPTED')
  self.attempted=True;row=dict(scope='owned synthetic AVD read-only native metadata',root_attempts=0,started_monotonic_ns=time.monotonic_ns())
  try:
   if os.environ.get('M06_NATIVE_READONLY')!='1' or not metadata.get('identity_ok') or metadata.get('known_stub') or metadata['properties']['ro.build.fingerprint'].get('value')!=FINGERPRINT:raise Unavailable('IDENTITY_NOT_ALLOWED')
   base=(metadata_proof or self.proof or PrivatePulse()).verify()
   row['private_proof_scope']=base.get('proof_scope','UNSPECIFIED_TEST_PROOF')
   row['root_attempts']=1
   raw,info=self.run(ADB+['root'],limit=4096,seconds=8)
   if not complete(info):raise Unavailable('ROOT_UNAVAILABLE')
   _,info=self.run(ADB+['wait-for-device'],limit=4096,seconds=8)
   if not complete(info):raise Unavailable('ROOT_RECONNECT_UNAVAILABLE')
   if self.query('id -u',128,2).strip()!='0':raise Unavailable('ROOT_ID_NOT_ZERO')
   self.rooted=True;row['root_uid']=0
   self.hal=process_list(self.query(PS_COMMAND,16384))
   self.hal['identity']=self.guard();row['hal']=self.hal
   raw=self.query('date +%s',128).strip()
   if not re.fullmatch('[0-9]{9,12}',raw):raise Unavailable('GUEST_CLOCK_UNAVAILABLE')
   self.start=int(raw);row['log_start_guest_epoch']=self.start
   try:
    self.objects=self.get_objects();row['objects']=[self.object_info(p) for p in self.objects]
   except Unavailable as e:row['objects']=unavailable(e.reason)
   row['before']=self.snapshot('before')
   if self.guard()!=self.hal['identity']:raise Unavailable('PID_REPLACED')
   row.update(status='AVAILABLE',reference_binary_match='UNKNOWN: hashes/build IDs anchor actual objects; no reference source mapping asserted')
  except Exception as e:row.update(unavailable(e.reason if isinstance(e,Unavailable) else 'ISOLATION_OR_IDENTITY_UNAVAILABLE'));row['error_class']=type(e).__name__
  self.save('privileged-prepare.json',row)
  return row
 def section(self,command,parser,limit=16384):
  started=time.monotonic_ns()
  try:
   text=self.query(command,limit);fields=parser(text)
   result=dict(status='AVAILABLE' if fields else 'UNAVAILABLE',fields=fields,empty_reason=None if fields else 'NO_RECOGNISED_FIELDS')
  except Unavailable as e:result=unavailable(e.reason)
  result.update(started_monotonic_ns=started,ended_monotonic_ns=time.monotonic_ns());return result
 def snapshot(self,phase):
  previous=self.deadline;self.deadline=time.monotonic()+8;started_ns=time.monotonic_ns()
  try:
   if not self.rooted or not self.hal:raise Unavailable('ROOT_OR_HAL_UNAVAILABLE')
   self.guard()
   object_reason=None
   try:objects=self.get_objects()
   except Unavailable as e:
    if self.objects is not None and e.reason=='NO_ALLOWED_MAPPED_OBJECT':raise Unavailable('OBJECT_SET_CHANGED')
    objects=None;object_reason=e.reason
   if self.objects is not None and objects is not None and objects!=self.objects:raise Unavailable('OBJECT_SET_CHANGED')
   row=dict(status='AVAILABLE',phase=phase,host_monotonic_ns=started_ns,hal_identity=self.hal['identity'],object_paths=objects,object_status='AVAILABLE' if objects is not None else 'UNAVAILABLE',object_reason=object_reason,
     alsa=self.section(ALSA_COMMAND,alsa_fields),snd=self.section('ls -ln /dev/snd',device_nodes),drivers=self.section(DRIVERS,drivers))
   mixer_start=time.monotonic_ns()
   try:
    tool=self.query('command -v tinymix',1024).strip()
    row['mixer']=self.section(tool,mixer) if tool in ('/system/bin/tinymix','/vendor/bin/tinymix') else unavailable('NO_ALLOWED_TINYMIX')
   except Unavailable as e:row['mixer']=unavailable(e.reason)
   row['mixer'].update(started_monotonic_ns=mixer_start,ended_monotonic_ns=time.monotonic_ns())
   now=self.query('date +%s',128).strip()
   if not re.fullmatch('[0-9]{9,12}',now):raise Unavailable('GUEST_CLOCK_UNAVAILABLE')
   end=int(now)
   if self.start is None or not self.start<=end<=self.start+180:raise Unavailable('LOG_WINDOW_BOUND')
   lo=max(self.start,end-20)
   awk=LOG_AWK.replace('START',str(lo)).replace('END',str(end))
   cmd=f"set -o pipefail; logcat -d -v epoch --pid={self.hal['pid']} -T '{lo}.000' '{TAG}:V' '*:S' | "+awk
   row['logs']=self.section(cmd,lambda text:log_enums(text,lo,end),8192)
   self.guard();row['ended_monotonic_ns']=time.monotonic_ns()
   return row
  except Unavailable as e:return dict(phase=phase,host_monotonic_ns=started_ns,ended_monotonic_ns=time.monotonic_ns(),**unavailable(e.reason))
  finally:self.deadline=previous

 def resume(self):
  try:
   data=json.loads((self.directory/'privileged-prepare.json').read_text())
   if data.get('status')!='AVAILABLE' or data.get('root_uid')!=0:raise Unavailable('PREPARE_UNAVAILABLE')
   if self.query('id -u',128).strip()!='0':raise Unavailable('ROOT_ID_NOT_ZERO')
   self.hal=data['hal'];pid=self.hal.get('pid')
   if type(pid) is not int or not 0<pid<10000000:raise Unavailable('HAL_ID_SCHEMA')
   self.rooted=True;self.guard()
   rows=data.get('objects');self.objects=[r['path'] for r in rows] if isinstance(rows,list) else None
   self.start=data['log_start_guest_epoch']
   if type(self.start) is not int or not 1000000000<=self.start<1000000000000:raise Unavailable('PREPARE_SCHEMA')
   if self.objects is not None:self.objects=allowed_objects('\n'.join(self.objects))
  except (OSError,ValueError,KeyError,Unavailable) as e:raise Unavailable(e.reason if isinstance(e,Unavailable) else 'PREPARE_SCHEMA') from None


def during(directory,nonce,source_evidence):
 if not re.fullmatch('[a-f0-9-]{36}',nonce):return unavailable('INVALID_NONCE')
 probe=NativeReadOnly(directory)
 try:
  probe.resume();row=probe.snapshot('PA_REQUEST_OBSERVATION')
 except Unavailable as e:row=unavailable(e.reason)
 row['nonce']=nonce
 row['source_evidence']={k:source_evidence.get(k) for k in ('nonce','requested','actual','session','native_session','frames','recording')}
 row['source_evidence_scope']='fixture-request held Capture/RecorderProof snapshot; not later current-input proof'
 row['flinger_reference']='active-'+nonce+'.json'
 row['qemu_reference']='mic-pa-'+nonce+'.json'
 return probe.save('privileged-during-'+nonce+'.json',row)


def flinger_fields(text):
 rows=[];current=None;tracks=False
 for line in text.splitlines():
  if 'Historical Thread Log' in line:current=None;tracks=False;continue
  m=re.fullmatch(r'Input thread 0x[0-9a-fA-F]+, name (AudioIn_[0-9A-Fa-f]+), tid ([0-9]+), type [0-9]+ \(RECORD\):',line.strip())
  if m:
   current=dict(name=m[1],tid=int(m[2]),tracks=[],gain_status='UNAVAILABLE',mute_status='UNAVAILABLE');rows.append(current);tracks=False;continue
  if current is None:continue
  if line.lstrip().startswith('-'):current=None;continue
  if 'Client(pid/uid)' in line and 'Session' in line:tracks=True;continue
  patterns={'io_handle':r'I/O handle: ([0-9]+)','rate':r'Sample rate: ([0-9]+) Hz','channels':r'Channel count: ([0-9]+)','source':r'Audio source: ([0-9]+) \(AUDIO_SOURCE_[A-Z_]+\)','effect_chains':r'([0-9]+) Effect Chains'}
  for key,pattern in patterns.items():
   value=re.fullmatch(pattern,line.strip())
   if value:current[key]=int(value[1])
  fmt=re.fullmatch(r'(HAL|Processing) format: (0x[0-9a-fA-F]+) \((AUDIO_FORMAT_[A-Z0-9_]+)\)',line.strip())
  if fmt:current[fmt[1].lower()+'_format']=dict(code=fmt[2],name=fmt[3])
  gain=re.fullmatch(r'Input gain: ([0-9]{1,4}(?:\.[0-9]{1,6})?)',line.strip())
  if gain:current['gain']=float(gain[1]);current['gain_status']='AVAILABLE'
  mute=re.fullmatch(r'(?:Input mute|Mic mute|Master mute): (on|off|true|false|0|1)',line.strip(),re.I)
  if mute:current['muted']=mute[1].lower() in ('on','true','1');current['mute_status']='AVAILABLE'
  track=re.match(r'\s*(yes|no|true|false|0|1)\s+([0-9]+)\s+([0-9]+)/([0-9]+)\s+([0-9]+)\s+([0-9]+)(?:\s|$)',line,re.I)
  if tracks and track and len(current['tracks'])<16:current['tracks'].append(dict(active=track[1].lower() in ('yes','true','1'),id=int(track[2]),pid=int(track[3]),uid=int(track[4]),session=int(track[5]),port=int(track[6])))
 for row in rows:row['track_status']='AVAILABLE' if row['tracks'] else 'UNAVAILABLE'
 return rows[:8]


class PlaybackWindow:
 def __init__(self,clock=time.monotonic_ns):self.clock=clock;self.lock=threading.Lock();self.start=None;self.end=None
 def begin(self):
  with self.lock:
   if self.start is None:self.start=self.clock()
 def finish(self):
  with self.lock:
   if self.start is not None and self.end is None:self.end=self.clock()
 def snapshot(self):
  with self.lock:return dict(started_monotonic_ns=self.start,ended_monotonic_ns=self.end,scope='owned paplay process interval; not exact acoustic onset or guest clock')


def overlap(section,window):
 a=section.get('started_monotonic_ns');b=section.get('ended_monotonic_ns');start=window.get('started_monotonic_ns');end=window.get('ended_monotonic_ns')
 if any(type(v) is not int for v in (a,b,start,end)) or b<a or end<start:return dict(status='UNKNOWN',reason='UNSEALED_OR_MISSING_WINDOW')
 intersection=max(0,min(b,end)-max(a,start))
 return dict(status='FULL' if start<=a<=b<=end else 'PARTIAL' if intersection else 'NONE',overlap_ns=intersection,scope='metadata read interval overlap only, not evidence every value/log event occurred during playback')


def finalise_during(directory,nonce,row,window,flinger):
 pa=window.snapshot();row['pa_process_window']=pa
 row['flinger_read_overlap']=overlap(flinger,pa)
 row['snapshot_overlap']=overlap(dict(started_monotonic_ns=row.get('host_monotonic_ns'),ended_monotonic_ns=row.get('ended_monotonic_ns')),pa)
 for key in ('alsa','snd','drivers','mixer','logs'):
  if key in row:row[key]['pa_read_overlap']=overlap(row[key],pa)
 requested=row.get('source_evidence',{}).get('native_session')
 matches=[dict(name=t.get('name'),io_handle=t.get('io_handle'),session=requested) for t in flinger.get('input_threads',[]) if type(requested) is int and any(track.get('session')==requested and track.get('active') is True for track in t.get('tracks',[]))]
 row['flinger_session_match']=dict(status='AVAILABLE' if matches else 'UNAVAILABLE',matches=matches,scope='only live parsed input track IDs compared with request snapshot; no historical/restored session attribution')
 (directory/('privileged-during-'+nonce+'.json')).write_text(json.dumps(row,indent=2))
 return row
