"""One fixed system-prompt asset, disabled by default. Never a user-audio tool."""
import argparse,asyncio,hashlib,json,os,signal,stat,subprocess,sys,time
from pathlib import Path
from contextlib import asynccontextmanager
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from backend.v2.speech import V2Speech
from backend.v2.runtime import settings
from backend.v2.files import read_checked,disable_core_dumps
from backend.dashscope import ProviderError,SpeechTaskError
TEXT='我没听清，可以再说一遍吗？'
MODEL='cosyvoice-v3-flash';VOICE='longanyang';RATE=24000;MAX_BYTES=RATE*2*6
SOURCE='19215a5de3f8ac2e1ca43639e510e32735530085'
PRODUCTION=('backend/dashscope.py','backend/timing.py','backend/v2/speech.py','backend/v2/runtime.py','backend/v2/files.py')
class GuardError(RuntimeError):pass

def digest(value):return hashlib.sha256(value).hexdigest()
def source_guard(tool_source):
    for ref,name in [(SOURCE,n) for n in PRODUCTION]+[(tool_source,'scripts/v2_clarification_asset.py')]:
        result=subprocess.run(['git','show',ref+':'+name],cwd=ROOT,capture_output=True,timeout=3)
        if result.returncode or result.stdout!=(ROOT/name).read_bytes():raise GuardError('source_mismatch')

def load_config():
    config=settings(environment={},service_env='/etc/little-buddy-v2/service.env')
    if config['tts']!=MODEL or config['voice']!=VOICE:raise GuardError('production_model_mismatch')
    return config

def save(path,value):
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2).encode()+b'\n'
    # Atomic replacement is only inside the exclusively-created private run directory.
    temp=path.with_suffix('.new')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(raw)
    os.replace(temp,path)

def private_output(path):
    if path.is_symlink() or path.exists():raise GuardError('output_exists')
    path.mkdir(mode=0o700) # parent must already exist; never create a public tree
    if stat.S_IMODE(path.stat().st_mode)!=0o700:raise GuardError('private_directory')

def plan():
    return dict(production_source=SOURCE,model=MODEL,voice=VOICE,text=TEXT,text_sha256=digest(TEXT.encode()),
                planned_unicode_characters=len(TEXT),format='pcm_s16le',channels=1,sample_rate=RATE,
                caps=dict(tts=1,asr=0,text_models=0,image=0,max_pcm_bytes=MAX_BYTES,worker_seconds=15,parent_seconds=20),
                automatic_retry=False,fallback=False,quota_live_verified=False,bill_verified=False,price=None,
                usage_policy='task_finished_characters_else_max_observed_cumulative_not_sum',
                material='fixed_system_prompt_not_user_content',apk_approved=False)

class AssetSpeech(V2Speech):
    def __init__(self,*args,checkpoint=None,**kwargs):
        super().__init__(*args,**kwargs);self.attempts=0;self.finished=False;self.usage_max=None;self.usage_final=None;self.checkpoint=checkpoint
    @asynccontextmanager
    async def speech_socket(self):
        if self.attempts>=1:raise GuardError('single_tts_cap')
        self.attempts+=1
        if self.checkpoint:self.checkpoint()
        async with super().speech_socket() as socket:yield socket
    def synthesize(self,text,rate):
        if text!=TEXT or rate!=RATE:raise GuardError('fixed_material_only')
        return super().synthesize(text,rate)
    def recognize(self,*args):raise GuardError('asr_forbidden')
    async def audio(self,task):
        async for message in task.socket:
            if isinstance(message,bytes):yield message;continue
            event,payload=task.event(message) # Original task_id validation precedes usage access.
            usage=payload.get('usage',{})
            value=usage.get('characters') if isinstance(usage,dict) else None
            if type(value) is int and 0<=value<=1000000:
                self.usage_max=value if self.usage_max is None else max(value,self.usage_max)
                if event=='task-finished':self.usage_final=value
            if event=='task-finished':self.finished=True;return
        raise ProviderError('unfinished synthesis')

def supervisor_guard():
    # Both parent and worker must inherit the same held global lock description.
    expected=os.stat('/var/lock/little-buddy/heavy.lock');actual=os.fstat(9)
    if (expected.st_dev,expected.st_ino)!=(actual.st_dev,actual.st_ino):raise GuardError('lock_required')
    import fcntl
    fcntl.flock(9,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if 'little-buddy-build-' not in Path('/proc/self/cgroup').read_text():raise GuardError('build_supervisor_required')

async def generate(out,tool_source):
    disable_core_dumps();source_guard(tool_source);config=load_config()
    report=plan();report.update(tool_source=tool_source,tool_sha256=digest(Path(__file__).read_bytes()),terminal='in_progress',tts_attempts=0,usage_characters=None,cleanup=dict(confirmed=False,pending=None))
    save(out/'result.json',report);speech=None;pcm=bytearray();started=time.monotonic()
    try:
        key=read_checked('/etc/little-buddy-v2/dashscope-api-key','provider_key',limit=4097).rstrip('\r\n')
        speech=AssetSpeech(None,key=key,**config)
        def charged():
            report['tts_attempts']=speech.attempts;report['calls']={'tts':speech.attempts,'asr':0,'llm':0,'image':0};save(out/'result.json',report)
        speech.checkpoint=charged
        async with asyncio.timeout(15):
            async with speech.synthesize(TEXT,RATE) as chunks:
                async for chunk in chunks:
                    if not isinstance(chunk,bytes) or len(pcm)+len(chunk)>MAX_BYTES:raise GuardError('pcm_capacity')
                    pcm.extend(chunk)
        if not speech.finished or not pcm or len(pcm)%2 or not any(pcm):raise GuardError('invalid_pcm')
        if speech.release_failed or speech.last_release is None or not speech.last_release['confirmed'] or any(not t.done() for t in speech.release_tasks):raise GuardError('release_unconfirmed')
        fd=os.open(out/'clarification.pcm',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f:f.write(pcm)
        report.update(terminal='asset_generated_not_auditioned',pcm_sha256=digest(pcm),pcm_bytes=len(pcm),samples=len(pcm)//2,duration_seconds=len(pcm)/(RATE*2))
    except BaseException as error:
        code='timeout' if isinstance(error,TimeoutError) else 'cancelled' if isinstance(error,asyncio.CancelledError) else 'failed'
        report.update(terminal=code,error_kind='quota' if isinstance(error,SpeechTaskError) and error.code in {'insufficient_quota','AllocationQuota.FreeTierOnly'} else 'provider' if isinstance(error,(SpeechTaskError,ProviderError)) else 'guard' if isinstance(error,GuardError) else 'other')
        if pcm:
            fd=os.open(out/'partial.pcm',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as f:f.write(pcm)
            report['partial_sha256']=digest(pcm);report['partial_bytes']=len(pcm)
    finally:
        pending=None if speech is None else sum(not t.done() for t in speech.release_tasks)
        report.update(elapsed_ms=round((time.monotonic()-started)*1000,3),tts_attempts=0 if speech is None else speech.attempts,
                      usage_characters=None if speech is None else speech.usage_final if speech.usage_final is not None else speech.usage_max,
                      usage_final=None if speech is None else speech.usage_final,usage_max=None if speech is None else speech.usage_max,
                      task_finished=False if speech is None else speech.finished,
                      calls=dict(tts=0 if speech is None else speech.attempts,asr=0,llm=0,image=0),
                      cleanup=dict(confirmed=bool(speech and not speech.release_failed and speech.last_release and speech.last_release['confirmed'] and pending==0),pending=pending))
        save(out/'result.json',report)
        pcm.clear()
    return 0 if report['terminal']=='asset_generated_not_auditioned' and report['cleanup']['confirmed'] else 1

def validate_result(out,source):
    try:
        path=out/'result.json';info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o600 or info.st_size>16384:return False,False,None
        raw=path.read_bytes();r=json.loads(raw)
        base=(r.get('tool_source')==source and r.get('model')==MODEL and r.get('voice')==VOICE and
              r.get('text')==TEXT and r.get('production_source')==SOURCE and r.get('caps')==plan()['caps'] and
              r.get('tool_sha256')==digest(Path(__file__).read_bytes()) and type(r.get('task_finished')) is bool and
              r.get('calls')==dict(tts=r.get('tts_attempts'),asr=0,llm=0,image=0) and
              all(type(v) is int for v in r.get('calls',{}).values()) and type(r.get('tts_attempts')) is int and 0<=r['tts_attempts']<=1 and
              type(r.get('cleanup',{}).get('confirmed')) is bool and
              r.get('terminal') in {'asset_generated_not_auditioned','timeout','cancelled','failed'})
        if not base:return False,False,digest(raw)
        cleanup=r['cleanup']['confirmed'] and type(r['cleanup'].get('pending')) is int and r['cleanup']['pending']==0
        if r['terminal']=='asset_generated_not_auditioned':
            pcm=out/'clarification.pcm';pinfo=pcm.lstat()
            valid=(stat.S_ISREG(pinfo.st_mode) and stat.S_IMODE(pinfo.st_mode)==0o600 and 0<pinfo.st_size<=MAX_BYTES and pinfo.st_size%2==0)
            if not valid:return False,False,digest(raw)
            audio=pcm.read_bytes()
            valid=(type(r.get('sample_rate')) is int and r['sample_rate']==RATE and type(r.get('channels')) is int and r['channels']==1 and r.get('format')=='pcm_s16le' and
                   type(r.get('samples')) is int and r['samples']==len(audio)//2 and type(r.get('pcm_bytes')) is int and r['pcm_bytes']==len(audio) and
                   r.get('pcm_sha256')==digest(audio) and r.get('task_finished') is True and r['tts_attempts']==1 and cleanup)
            if not valid:return False,False,digest(raw)
        return True,bool(cleanup),digest(raw)
    except (OSError,ValueError,TypeError,KeyError):return False,False,None

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare',action='store_true');mode.add_argument('--execute',action='store_true')
    parser.add_argument('--tool-source');parser.add_argument('--output',type=Path);parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    if not args.prepare and not args.execute:print('disabled');return 0
    if args.output is None or not args.tool_source:raise GuardError('admission')
    source_guard(args.tool_source);load_config()
    out=args.output.absolute()
    if args.prepare:
        private_output(out);save(out/'prepare.json',dict(plan(),production_model_voice_confirmed=True,tool_source=args.tool_source,tool_sha256=digest(Path(__file__).read_bytes()),actual_calls=0));return 0
    supervisor_guard()
    if args.worker:
        if out.is_symlink() or stat.S_IMODE(out.stat().st_mode)!=0o700 or (out/'result.json').exists():raise GuardError('one_worker_only')
        return asyncio.run(generate(out,args.tool_source))
    private_output(out)
    child=subprocess.Popen([sys.executable,'-I','-B',str(Path(__file__).resolve()),'--execute','--worker','--tool-source',args.tool_source,'--output',str(out)],pass_fds=(9,),start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    forced=False
    try:code=child.wait(timeout=20)
    except subprocess.TimeoutExpired:
        forced=True;os.killpg(child.pid,signal.SIGTERM)
        try:code=child.wait(timeout=1)
        except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);code=child.wait(timeout=1)
    valid,cleanup,sha=validate_result(out,args.tool_source)
    save(out/'supervisor.json',dict(worker_exit=code,forced_exit=forced,automatic_retry=False,artifact_valid=valid,result_sha256=sha,cleanup_confirmed=cleanup and not forced))
    return code or int(forced or not valid or not cleanup)

if __name__=='__main__':
    try:sys.exit(main())
    except Exception:print('asset_admission_failed',file=sys.stderr);sys.exit(2)
