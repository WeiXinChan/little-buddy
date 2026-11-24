"""One legal synthetic TTS -> in-memory resample -> real ASR; no body/audio files."""
import asyncio,json,sys,time,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.dashscope import DashScope,http_client

async def main():
    from backend.animal.cloud import disable_core_dumps
    disable_core_dumps()
    row=dict(input='synthetic_only',real_child=False,acoustics=False)
    try:
        async with http_client() as http:
            speech=DashScope.from_environment(http)
            row.update(region='cn-beijing',asr=speech.asr,tts=speech.tts,voice=speech.voice)
            start=time.monotonic();first=None;pcm=bytearray()
            async with asyncio.timeout(12):
                async with speech.synthesize('合成测试，小猫去月球。',24000) as frames:
                    async for frame in frames:
                        if first is None:first=round((time.monotonic()-start)*1000)
                        pcm.extend(frame)
                        if len(pcm)>480000:raise ValueError('capacity')
            row.update(tts_first_pcm_ms=first,tts_total_ms=round((time.monotonic()-start)*1000),tts_samples=len(pcm)//2)
            result=subprocess.run(['ffmpeg','-v','error','-f','s16le','-ar','24000','-ac','1',
                '-i','pipe:0','-f','s16le','-ar','16000','-ac','1','pipe:1'],
                input=pcm,capture_output=True,check=True,timeout=4)
            pcm.clear();start=time.monotonic()
            async with asyncio.timeout(12):
                async with speech.recognize(16000) as asr:
                    for offset in range(0,len(result.stdout),6400):await asr.write(result.stdout[offset:offset+6400])
                    text=await asr.finish()
            row.update(asr_ms=round((time.monotonic()-start)*1000),recognized_cat='猫' in text,recognized_moon='月球' in text,passed=('猫' in text and '月球' in text))
    except Exception as failure:row.update(passed=False,error=type(failure).__name__)
    print(json.dumps(row),flush=True)
if __name__=='__main__':asyncio.run(main())
