"""Continuous real KWS clock: standalone negation then independent commands."""
import sys,array,wave,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent));from reset_probe import model
root=Path('app/src/androidTest/assets/m06-commands');rows=[];tsv=[]
def read(name):
 with wave.open(str(root/(name+'.wav'))) as w:return array.array('h',w.readframes(w.getnframes()))
for command in ['cancel','exit']:
 for gap in [1.6,4.0]:
  a=read('deny_prefix')[:-16000];a.extend([0]*int(gap*16000));a.extend(read(command)[8000:]);a.extend([0]*32000)
  name=f'deny_pair_{command}_{gap}';k=model();s=k.create_stream();hits=[];last=-1
  for pos in range(0,len(a),320):
   s.accept_waveform(16000,[x/32768 for x in a[pos:pos+320]])
   while k.is_ready(s):
    k.decode_stream(s);r=k.keyword_spotter.get_result(s)
    if r.keyword:
     tail=int((r.timestamps[-1]+.12)*16000)
     if tail>last:last=tail;hits.append(dict(frame=pos//320,name=r.keyword,start=int(r.timestamps[0]*16000),end=tail));break
  p=root/(name+'.wav')
  with wave.open(str(p),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(a.tobytes())
  expected=('取消' if command=='cancel' else '退出管理') if gap==4 else 'NONE'
  tsv.append('case\t'+name+'\ttrue\t'+expected)
  for h in hits:tsv.append('hit\t'+str(h['frame'])+'\t'+h['name']+'\t'+str(h['start'])+'\t'+str(h['end']))
  rows.append(dict(name=name,expected=expected,hits=hits))
(root/'deny-pair.tsv').write_text('\n'.join(tsv)+'\n')
Path('docs/testing/v2/r100/deny-pair-native.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n');print(rows)
