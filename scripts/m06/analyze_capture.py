"""Offline alignment of ONLY the nonce/SHA-validated synthetic enter AudioRecord probe."""
import array,hashlib,json,math,sys,wave
from pathlib import Path
ENTER='c53eb146203afc87fd8092f60721e49a20d30baaa0811da715788a40fe582e34'
source=Path('app/src/androidTest/assets/m06-commands/enter.wav')
assert hashlib.sha256(source.read_bytes()).hexdigest()==ENTER
with wave.open(str(source)) as wav:
 assert (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())==(16000,1,2)
 data=wav.readframes(wav.getnframes())
def samples(raw):
 a=array.array('h');a.frombytes(raw)
 if sys.byteorder!='little':a.byteswap()
 return a
def stats(a):
 return dict(samples=len(a),seconds=len(a)/16000,nonzero=sum(v!=0 for v in a),clipped=sum(abs(v)>=32767 for v in a),peak=max(map(abs,a),default=0),rms=math.sqrt(sum(v*v for v in a)/max(1,len(a))))
def bins(a):return [math.sqrt(sum(v*v for v in a[p:p+160])/len(a[p:p+160])) for p in range(0,len(a),160)]
def corr(a,b):
 if not a or len(a)!=len(b):return 0
 aa=sum(a)/len(a);bb=sum(b)/len(b)
 top=sum((x-aa)*(y-bb) for x,y in zip(a,b));bot=math.sqrt(sum((x-aa)**2 for x in a)*sum((y-bb)**2 for y in b))
 return top/bot if bot else 0
found=0
for meta in Path(sys.argv[1]).glob('synthetic-*/capture.json'):
 row=json.loads(meta.read_text());raw=(meta.parent/'capture.s16le').read_bytes()
 assert row['source_sha256']==ENTER and hashlib.sha256(raw).hexdigest()==row['capture_sha256']
 assert len(raw)<=256000 and row['window_limit_ms']==8000 and row['sample_limit']==128000
 assert (row['sample_rate'],row['channels'],row['encoding'])==(16000,1,'signed PCM16 little endian')
 src=samples(data);cap=samples(raw);s=bins(src);c=bins(cap);best=[]
 for ratio in [.25,.5,1,2,4]:
  warped=[s[min(int(n/ratio),len(s)-1)] for n in range(int(len(s)*ratio))]
  choices=[]
  for offset in range(-len(warped)+10,len(c)-10):
   left=max(0,offset);right=min(len(c),offset+len(warped))
   if right-left<min(50,len(warped)):continue
   score=corr(warped[left-offset:right-offset],c[left:right]);choices.append((score,offset,right-left))
  if choices:
   score,offset,overlap=max(choices);best.append(dict(capture_duration_ratio=ratio,lag_ms=offset*10,envelope_correlation=score,overlap_ms=overlap*10))
 result=dict(nonce=row['nonce'],source=stats(src),capture=stats(cap),source_one_second=[stats(src[n:n+16000]) for n in range(0,len(src),16000)],capture_one_second=[stats(cap[n:n+16000]) for n in range(0,len(cap),16000)],alignment=best,
  scope='diagnostic envelope alignment; no threshold/model alteration or format root-cause conclusion',same_installed_android_model_replay=dict(source=row.get('source_replay'),capture=row.get('capture_replay')))
 host_meta=Path(sys.argv[1]).parent/('mic-host-'+row['nonce']+'.json')
 if host_meta.is_file():
  hm=json.loads(host_meta.read_text());hb=(host_meta.parent/hm['file']).read_bytes()
  assert hm['capture_sha256']==hashlib.sha256(hb).hexdigest() and hm['fixture_sha256']==ENTER and hm['nonce']==row['nonce'] and hm['sha256'] and hm['name']=='enter'
  assert hm['rate']==16000 and hm['channels']==1 and len(hb)<=256000
  host=samples(hb);result['host_monitor']=dict(metadata=hm,summary=stats(host),one_second=[stats(host[n:n+16000]) for n in range(0,len(host),16000)])
  comparisons=[]
  for label,left,right in [('source_to_monitor',s,bins(host)),('monitor_to_guest',bins(host),c)]:
   choices=[]
   for lag in range(-len(left)+10,len(right)-10):
    lo=max(0,lag);hi=min(len(right),lag+len(left))
    if hi-lo>=min(50,len(left)):choices.append((corr(left[lo-lag:hi-lag],right[lo:hi]),lag,hi-lo))
   if choices:
    score,lag,n=max(choices);comparisons.append(dict(pair=label,ratio=1,lag_ms=lag*10,envelope_correlation=score,overlap_ms=n*10))
  result['three_point_alignment']=comparisons
 (meta.parent/'alignment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False));found+=1
assert found==1, f'exactly one authorized enter capture required, got {found}'
