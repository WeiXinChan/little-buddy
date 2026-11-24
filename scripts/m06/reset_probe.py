import sys,json,wave,array
from pathlib import Path
import sherpa_onnx
m=Path('app/src/main/assets/wake');suffix='epoch-13-avg-2-chunk-16-left-64'
def model():return sherpa_onnx.KeywordSpotter(tokens=str(m/'tokens.txt'),encoder=str(m/f'encoder-{suffix}.int8.onnx'),decoder=str(m/f'decoder-{suffix}.onnx'),joiner=str(m/f'joiner-{suffix}.int8.onnx'),keywords_file=str(m/'manage.txt'),num_threads=1,keywords_score=1.5,keywords_threshold=.25,num_trailing_blanks=2)
def main():
 rows=[]
 for reset in [False,True]:
  k=model();s=k.create_stream();hits=[];position=0
  for name in ['enter','cancel','exit','enter']:
   with wave.open('app/src/androidTest/assets/m06-commands/'+name+'.wav','rb') as w:pcm=array.array('h',w.readframes(w.getnframes()))
   for pos in range(0,len(pcm),320):
    data=pcm[pos:pos+320];s.accept_waveform(16000,[x/32768 for x in data]);position+=len(data)
    while k.is_ready(s):
     k.decode_stream(s);r=k.keyword_spotter.get_result(s)
     if r.keyword:
      hits.append(dict(keyword=r.keyword,at_ms=position//16,timestamps=list(r.timestamps)))
      if reset:k.reset_stream(s)
  rows.append(dict(reset=reset,hits=hits))
 Path('docs/testing/v2/r100/reset-probe.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
 print([(r['reset'],len(r['hits']),r['hits'][:3]) for r in rows])

if __name__=="__main__":main()
