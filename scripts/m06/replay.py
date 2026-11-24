"""Same real native model/default Android decoding policy; export raw per-frame KWS evidence for Kotlin replay."""
import array,json,wave
from pathlib import Path
import sherpa_onnx
m=Path('app/src/main/assets/wake');suffix='epoch-13-avg-2-chunk-16-left-64';root=Path('app/src/androidTest/assets/m06-commands')
k=sherpa_onnx.KeywordSpotter(tokens=str(m/'tokens.txt'),encoder=str(m/f'encoder-{suffix}.int8.onnx'),decoder=str(m/f'decoder-{suffix}.onnx'),joiner=str(m/f'joiner-{suffix}.int8.onnx'),keywords_file=str(m/'manage.txt'),num_threads=1,keywords_score=1.5,keywords_threshold=.25,num_trailing_blanks=2)
rows=[]
for row in json.loads((root/'cases.json').read_text())['cases']:
 with wave.open(str(root/(row['name']+'.wav')),'rb') as w:pcm=array.array('h',w.readframes(w.getnframes()))
 pcm.extend([0]*19200);stream=k.create_stream();hits=[];delivered=-1
 for pos in range(0,len(pcm),320):
  data=pcm[pos:pos+320];stream.accept_waveform(16000,[x/32768 for x in data])
  while k.is_ready(stream):
   k.decode_stream(stream);r=k.keyword_spotter.get_result(stream)
   if r.keyword:
    tail=int((r.timestamps[-1]+.12)*16000)
    if tail>delivered:
     delivered=tail;hits.append(dict(frame=pos//320,name=r.keyword,start=int(r.timestamps[0]*16000),end=tail));break
 rows.append(dict(**row,hits=hits))
(root/'native-replay.json').write_text(json.dumps({'version':sherpa_onnx.__version__,'score':1.5,'threshold':.25,'trailing_blanks':2,'threads':1,'reset':False,'model_type':'Python native auto-detection from same zipformer2 ONNX metadata; Android explicitly zipformer2','cases':rows},ensure_ascii=False,indent=2)+'\n')
print('real native frame replays',len(rows))

lines=[]
for row in rows:
 lines.append("case\t"+row["name"]+"\t"+str(row["managed"]).lower()+"\t"+(row["expected"] or "NONE"))
 for h in row["hits"]:lines.append("hit\t"+str(h["frame"])+"\t"+h["name"]+"\t"+str(h["start"])+"\t"+str(h["end"]))
(root/"native-replay.tsv").write_text("\n".join(lines)+"\n")
