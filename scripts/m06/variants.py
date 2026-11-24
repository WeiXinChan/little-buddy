"""DSP-only variants of authorized synthetic files. No human recordings or adaptive expectations."""
import array,hashlib,json,subprocess,wave
from pathlib import Path
root=Path('app/src/androidTest/assets/m06-commands');rows=[]
def read(name):
 with wave.open(str(root/(name+'.wav')),'rb') as w:return w.readframes(w.getnframes())
def write(name,data,expected,managed,source):
 p=root/(name+'.wav')
 with wave.open(str(p),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(data)
 rows.append(dict(name=name,expected=expected,managed=managed,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),source=source))
for base,expected,managed in [('enter','进入管理',False),('enter_polite','进入管理',False),('enter_open','进入管理',False),('cancel','取消',True),('exit','退出管理',True),('near',None,False),('negative',None,False),('discussion',None,False),('cancel_negative',None,True),('cancel_discussion',None,True)]:
 rows.append(dict(name=base,expected=expected,managed=managed,sha256=hashlib.sha256((root/(base+'.wav')).read_bytes()).hexdigest(),source='authorized-tts provenance.json'))
 for rate,gain in [(.85,.5),(1.15,1.4)]:
  data=subprocess.run(['ffmpeg','-v','error','-f','s16le','-ar','16000','-ac','1','-i','pipe:0','-af',f'atempo={rate},volume={gain}','-f','s16le','pipe:1'],input=read(base),capture_output=True,check=True).stdout
  write(base+('_slow' if rate<1 else '_fast'),data,expected,managed,f'{base}: atempo={rate} volume={gain}')
 if expected:
  noise=array.array('h',[4500 if i%2 else -4500 for i in range(640)]).tobytes()
  write(base+'_noise',bytes(8000)+noise+bytes(6400)+read(base),expected,managed,f'{base}: 40ms transient then 200ms quiet')
for gap in [.6,1.6,4.0]:
 for base in ['cancel','exit']:
  write(f'negative_pause_{base}_{gap}',read('deny_prefix')+bytes(int(gap*32000))+read(base),None,True,f'authorized deny_prefix + {gap}s pause + {base}; no expectation changed')
for base in ['cancel','exit']:
 write(base+'_continued_discussion',read(base)[:-32000]+bytes(6400)+read('discussion_suffix')[16000:],None,True,f'{base} +200ms+ continued discussion, padding removed')
(root/'cases.json').write_text(json.dumps({'cases':rows},ensure_ascii=False,indent=2)+'\n')
print('cases',len(rows))
