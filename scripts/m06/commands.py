"""Legal synthetic-only fixtures; espeak-ng GPL-3 tool, generated speech has no human recording."""
import argparse,hashlib,json,subprocess,wave
from pathlib import Path
CASES={'enter':'瓦力瓦力进入管理页面','cancel':'取消','exit':'退出管理页面','near':'哪里哪里进入公园里面','negative':'瓦力瓦力不要进入管理页面','discussion':'我在讲瓦力瓦力进入管理页面这个句子','cancel_negative':'不要取消','cancel_discussion':'故事里面提到了取消这个词','wake':'瓦力瓦力','enter_polite':'瓦力瓦力请进入管理页面','enter_open':'瓦力瓦力打开管理页面','deny_prefix':'不要','discussion_suffix':'这个词是故事里的台词'}
def generate(root):
 root.mkdir(parents=True,exist_ok=True); rows=[]
 for name,text in CASES.items():
  wav=subprocess.run(['espeak-ng','-v','cmn','-s','150','--stdout',text],capture_output=True,check=True).stdout
  pcm=subprocess.run(['ffmpeg','-v','error','-i','pipe:0','-f','s16le','-ar','16000','-ac','1','pipe:1'],input=wav,capture_output=True,check=True).stdout
  pcm=bytes(16000)+pcm+bytes(32000)
  with wave.open(str(root/(name+'.wav')),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(pcm)
  rows.append(dict(name=name,text=text,source='espeak-ng cmn -s150; locally generated synthetic Mandarin',sha256=hashlib.sha256((root/(name+'.wav')).read_bytes()).hexdigest(),frames=len(pcm)//2))
 (root/'provenance.json').write_text(json.dumps(dict(tool=subprocess.check_output(['espeak-ng','--version'],text=True).splitlines()[0],tool_license='GPL-3.0-or-later; no human audio input; generated synthetic speech test fixtures',rows=rows),ensure_ascii=False,indent=2)+'\n')
def probe(root,out):
 import sherpa_onnx,array
 model=Path('app/src/main/assets/wake');suffix='epoch-13-avg-2-chunk-16-left-64'
 kws=sherpa_onnx.KeywordSpotter(tokens=str(model/'tokens.txt'),encoder=str(model/f'encoder-{suffix}.int8.onnx'),decoder=str(model/f'decoder-{suffix}.onnx'),joiner=str(model/f'joiner-{suffix}.int8.onnx'),keywords_file=str(model/'manage.txt'),num_threads=1,keywords_score=1.5,keywords_threshold=0.25,num_trailing_blanks=2)
 rows=[]
 for name in CASES:
  with wave.open(str(root/(name+'.wav')),'rb') as w:pcm=array.array('h',w.readframes(w.getnframes()))
  stream=kws.create_stream(); hits=[]
  for pos in range(0,len(pcm),320):
   stream.accept_waveform(16000,[x/32768 for x in pcm[pos:pos+320]])
   while kws.is_ready(stream):
    kws.decode_stream(stream);r=kws.get_result(stream)
    if r: hits.append(dict(keyword=r,at_ms=pos//16)); kws.reset_stream(stream)
  rows.append(dict(name=name,hits=hits))
 Path(out).write_text(json.dumps({'sherpa_version':sherpa_onnx.__version__,'mode':'real model 320 sample frames CPU1; raw KWS hits, not production command decisions','rows':rows},ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['generate','probe']);p.add_argument('--root',default='app/src/androidTest/assets/m06-commands');p.add_argument('--out',default='docs/testing/v2/r100/kws-raw.json');a=p.parse_args();generate(Path(a.root)) if a.action=='generate' else probe(Path(a.root),a.out)
