"""Compare graph competition without changing production thresholds or corpus."""
import sys,array,wave,json,tempfile,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from reset_probe import model
rows=[]
for name in ['enter_polite','enter_polite_slow','enter_polite_fast','enter_open','enter_open_slow','enter_open_fast']:
 k=model()
 with wave.open('app/src/androidTest/assets/m06-commands/'+name+'.wav') as w:p=array.array('h',w.readframes(w.getnframes()))
 for mode in ['all','only','gain_restored']:
  kw=Path('app/src/main/assets/wake/manage.txt').read_text().splitlines()[3 if 'polite' in name else 4]
  s=k.create_stream() if mode=='all' else k.create_stream(keywords=kw)
  hits=[]
  for pos in range(0,len(p)+32000,320):
   a=p[pos:pos+320] if pos<len(p) else [0]*320
   if mode=='gain_restored' and name.endswith('_slow'):a=[max(-32768,min(32767,x*2)) for x in a]
   s.accept_waveform(16000,[x/32768 for x in a])
   while k.is_ready(s):
    k.decode_stream(s);r=k.keyword_spotter.get_result(s)
    if r.keyword:hits.append({'frame':pos//320,'name':r.keyword,'timestamps':list(r.timestamps)})
  rows.append({'name':name,'graph':mode,'hits':hits})
Path('docs/testing/v2/r100/slow-probe.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
print([(x['name'],x['graph'],len(x['hits'])) for x in rows])
