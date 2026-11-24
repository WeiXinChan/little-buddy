"""Use ONLY the existing project runtime's authorized TTS; synthetic corpus only. No env/body logging."""
import asyncio,os,sys,subprocess,wave,json,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from commands import CASES
from backend.dashscope import DashScope,http_client
async def main():
 pid=int(subprocess.check_output(['systemctl','show','little-buddy-v1.service','-p','MainPID','--value'],text=True))
 for entry in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0'):
  key,_,value=entry.partition(b'=');name=key.decode('ascii',errors='ignore')
  if name.startswith('DASHSCOPE_') or name=='CREDENTIALS_DIRECTORY':os.environ[name]=value.decode()
 root=Path('app/src/androidTest/assets/m06-commands');rows=[]
 old={r['name']:r for r in json.loads((root/'provenance.json').read_text()).get('rows',[])}
 async with http_client() as http:
  speech=DashScope.from_environment(http)
  for name,text in CASES.items():
   if name in old and old[name]["text"]==text and hashlib.sha256((root/(name+".wav")).read_bytes()).hexdigest()==old[name]["sha256"]:
    rows.append(old[name]);continue
   pcm=bytearray()
   async with asyncio.timeout(15):
    async with speech.synthesize(text,24000) as chunks:
     async for chunk in chunks:
      pcm.extend(chunk)
      if len(pcm)>960000:raise ValueError('synthetic bound')
   data=subprocess.run(['ffmpeg','-v','error','-f','s16le','-ar','24000','-ac','1','-i','pipe:0','-f','s16le','-ar','16000','-ac','1','pipe:1'],input=pcm,capture_output=True,check=True).stdout
   data=bytes(16000)+data+bytes(32000)
   with wave.open(str(root/(name+'.wav')),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(data)
   rows.append(dict(name=name,text=text,frames=len(data)//2,sha256=hashlib.sha256((root/(name+'.wav')).read_bytes()).hexdigest()))
  result=dict(source='existing project authorized DashScope synthetic-only TTS',model=speech.tts,voice=speech.voice,region='cn-beijing',sample_rate=16000,license_scope='existing authorized project API terms; agent-authored synthetic text; no human recording; no new paid service',rows=rows)
 (root/'provenance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'generated':len(rows),'model':speech.tts,'voice':speech.voice,'synthetic_only':True}))
if __name__=='__main__':
 try:asyncio.run(main())
 except Exception as e:print(json.dumps({'error_class':type(e).__name__}));sys.exit(1)
