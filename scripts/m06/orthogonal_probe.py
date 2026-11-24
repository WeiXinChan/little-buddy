"""Orthogonal real-model replay; preserves production graph/threshold and failures."""
import sys,array,wave,json,subprocess,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from reset_probe import model
import sherpa_onnx
root=Path('app/src/androidTest/assets/m06-commands');rows=[]
for name in ['enter_polite','enter_open','negative','cancel_discussion']:
 with wave.open(str(root/(name+'.wav'))) as w:base=w.readframes(w.getnframes())
 for variant,filters in [('original',None),('volume','volume=0.5'),('atempo','atempo=0.85'),('combined','atempo=0.85,volume=0.5')]:
  data=base if filters is None else subprocess.run(['ffmpeg','-v','error','-f','s16le','-ar','16000','-ac','1','-i','pipe:0','-af',filters,'-f','s16le','pipe:1'],input=base,capture_output=True,check=True).stdout
  for finished in [False,True]:
   k=model();s=k.create_stream();p=array.array('h');p.frombytes(data);p.extend([0]*32000);hits=[];decodes=0
   def drain(pos):
    global decodes
    while k.is_ready(s):
     k.decode_stream(s);decodes+=1;r=k.keyword_spotter.get_result(s)
     if r.keyword and not hits:hits.append({'name':r.keyword,'at_sample':pos,'timestamps':list(r.timestamps)})
   for pos in range(0,len(p),320):
    s.accept_waveform(16000,[x/32768 for x in p[pos:pos+320]]);drain(pos+320)
   if finished:s.input_finished();drain(len(p))
   rows.append(dict(name=name,variant=variant,input_finished=finished,decodes=decodes,pcm_sha256=hashlib.sha256(data).hexdigest(),hits=hits))
assets=Path('app/src/main/assets/wake')
result={'python_library':sherpa_onnx.__version__,'config':{'score':1.5,'threshold':.25,'trailing_blanks':2,'active_paths':4,'threads':1,'frame':320,'sample_rate':16000,'tail_zero_samples':32000},'model_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in assets.glob('*.onnx')},'cases':rows,'native_slow_TTS':'NOT_RUN; atempo is DSP, not natural slow pronunciation'}
Path('docs/testing/v2/r100/orthogonal-probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print([(r['name'],r['variant'],r['input_finished'],bool(r['hits'])) for r in rows])
