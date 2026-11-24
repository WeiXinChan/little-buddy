from reset_probe import model
from commands import CASES
import array,wave,math,json
from pathlib import Path
rows=[]
for name in CASES:
 k=model();s=k.create_stream();hits=[];first=None;last=0
 with wave.open('app/src/androidTest/assets/m06-commands/'+name+'.wav','rb') as w:pcm=array.array('h',w.readframes(w.getnframes()))
 for pos in range(0,len(pcm),320):
  data=pcm[pos:pos+320]
  if data and math.sqrt(sum(x*x for x in data)/len(data))>120:
   if first is None:first=pos/16000
   last=(pos+len(data))/16000
  s.accept_waveform(16000,[x/32768 for x in data])
  while k.is_ready(s):
   k.decode_stream(s);r=k.keyword_spotter.get_result(s)
   if r.keyword:
    hits.append(dict(keyword=r.keyword,start=r.timestamps[0],end=r.timestamps[-1]+.12));k.reset_stream(s)
 rows.append(dict(name=name,first=first,last=last,hits=hits))
Path('docs/testing/v2/r100/boundary-measurements.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
print(rows)
