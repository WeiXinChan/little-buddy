"""Fixed synthetic ASR pair. Default off; execute is for separately authorized root only."""
import argparse, asyncio, hashlib, json, os, re, signal, stat, subprocess, sys, time, wave, io
from pathlib import Path
from contextlib import asynccontextmanager
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from backend.v2.speech import V2Speech
from backend.v2.runtime import settings
from backend.v2.files import read_checked,disable_core_dumps
from backend.dashscope import SpeechTask,Recognition,SpeechTaskError
SOURCE='7b421b17f03399250b8dcc9b1bd781f782141f5e'
FIXTURE=Path('/home/ubuntu/tech/v2-delivery/performance-aiff-private/ordinary-introduction-16k.wav')
FIXTURE_SHA='0ce8f590d98384383fab2d6004ae206a30f34d20c19372a34c48c0bfcf160801'
REFERENCE='你好，请用一句话介绍你自己'
MODEL='fun-asr-realtime';RATE=16000;SAMPLES=49413;QUIET=.300;CHUNK=6400
PRODUCTION=('backend/dashscope.py','backend/timing.py','backend/v2/speech.py','backend/v2/runtime.py','backend/v2/files.py','scripts/with-build-lock')
class GuardError(RuntimeError):pass
def digest(data):return hashlib.sha256(data).hexdigest()
def normalized(text):return re.sub(r'[\s，。！？、,.!?]','',text)
def text_meta(text):return dict(sha256=digest(text.encode()),length=len(text),reference_normalizedeq=normalized(text)==normalized(REFERENCE))
def source_guard(tool_source):
    for ref,name in [(SOURCE,n) for n in PRODUCTION]+[(tool_source,'scripts/v2_asr_pair.py')]:
        r=subprocess.run(['git','-c','safe.directory='+str(ROOT),'show',ref+':'+name],cwd=ROOT,capture_output=True,timeout=3)
        if r.returncode or r.stdout!=(ROOT/name).read_bytes():raise GuardError('source_mismatch')
def load_config():
    config=settings(environment={},service_env='/etc/little-buddy-v2/service.env')
    if config['asr']!=MODEL:raise GuardError('model_mismatch')
    return config

def fixture():
    # Fixed path AND full-file hash, no arbitrary audio arguments, no symlink.
    info=FIXTURE.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size>110000:raise GuardError('fixture_identity')
    raw=FIXTURE.read_bytes()
    if digest(raw)!=FIXTURE_SHA:raise GuardError('fixture_identity')
    with wave.open(io.BytesIO(raw),'rb') as f:
        if (f.getnchannels(),f.getsampwidth(),f.getframerate(),f.getnframes(),f.getcomptype())!=(1,2,RATE,SAMPLES,'NONE'):raise GuardError('fixture_format')
        pcm=f.readframes(SAMPLES)
    if len(pcm)!=SAMPLES*2:raise GuardError('fixture_capacity')
    return pcm

def plan():
    return dict(production_source=SOURCE,model=MODEL,fixture_sha256=FIXTURE_SHA,samples=SAMPLES,
                duration_seconds=SAMPLES/RATE,quiet_seconds=QUIET,chunk_bytes=CHUNK,format='pcm_s16le',sample_rate=RATE,
                caps=dict(asr=2,text=0,tts=0,image=0,worker_seconds=19,parent_seconds=20,cleanup_seconds=.5),
                automatic_retry=False,fallback=False,usage_unit='provider_numeric_fields_only_cumulative_max_not_sum',
                price=None,bill_verified=False,quota_live_verified=False,material='fixed_synthetic_not_family_audio')

class RealClock:
    def now(self):return time.monotonic()
    async def until(self,target):await asyncio.sleep(max(0,target-self.now()))

class Ledger:
    def __init__(self,save_report):self.save_report=save_report;self.calls=0;self.stopped=False
    def reserve(self,row):
        if self.stopped or self.calls>=2:raise GuardError('cap')
        self.calls+=1;row['socket_attempts']=1
        # Must finish durable checkpoint before DNS/TLS/run-task I/O, never retry reservation.
        self.save_report()

class MeasuredTask(SpeechTask):
    def __init__(self,socket,row,checkpoint,stamp):
        super().__init__(socket);self.row=row;self.checkpoint=checkpoint;self.stamp=stamp
    async def command(self,action,**payload):
        field={'run-task':'starts','finish-task':'finishes'}.get(action)
        if field is None or self.row[field]>=1:raise GuardError('task_cap')
        self.row[field]+=1
        self.checkpoint() # disk before each task command I/O
        if action=='finish-task':self.stamp('finish')
        await super().command(action,**payload)
    def event(self,message):
        event,payload=super().event(message) # validate task ID before accepting usage
        usage=payload.get('usage',{})
        if isinstance(usage,dict):
            # Never output arbitrary provider keys/strings. Missing remains null/{}.
            for key in ('duration','seconds','audio_duration','characters'):
                value=usage.get(key)
                if type(value) in (int,float) and 0<=value<=1000000:
                    old=self.row['usage_max'].get(key)
                    self.row['usage_max'][key]=value if old is None else max(old,value)
                    if event=='task-finished':self.row['usage_final'][key]=value
        if event=='task-finished':self.row['task_finished']=True
        return event,payload

class PairSpeech(V2Speech):
    def __init__(self,*args,ledger,row,checkpoint,stamp,**kwargs):
        super().__init__(*args,**kwargs);self.ledger=ledger;self.row=row;self.checkpoint=checkpoint;self.stamp=stamp;self.reader=None
    @asynccontextmanager
    async def recognize(self,rate):
        if rate!=RATE:raise GuardError('rate')
        self.ledger.reserve(self.row)
        async with self.speech_socket() as socket:
            task=MeasuredTask(socket,self.row,self.checkpoint,self.stamp)
            await task.start('asr','recognition',self.asr,dict(format='pcm',sample_rate=rate))
            self.stamp('ready');rec=Recognition(task);self.reader=rec.results
            try:yield rec
            finally:await rec.close()
    def synthesize(self,*args):raise GuardError('forbidden')
    def answer(self,*args,**kwargs):raise GuardError('forbidden')

def new_row(mode):
    return dict(mode=mode,terminal='pending',socket_attempts=0,starts=0,finishes=0,task_finished=False,
                usage_max={},usage_final={},timing_ms={},readtaskpending=None,cleanup_confirmed=False)

async def trial(mode,pcm,row,factory,clock=None):
    clock=clock or RealClock();origin=clock.now();end=origin+SAMPLES/RATE
    row['timing_ms'].update(captureorigin=round(-SAMPLES/RATE*1000,3),expression_end=0)
    def stamp(name):row['timing_ms'][name]=round((clock.now()-end)*1000,3)
    speech=factory(row,stamp)
    async def work():
        if mode=='old':await clock.until(end+QUIET)
        stamp('open')
        async with speech.recognize(RATE) as rec:
            # New availability follows ORIGINAL capture origin. Late ready can catch up
            # available backlog; no pacing re-anchor and no future bytes.
            written=bytearray()
            for offset in range(0,len(pcm),CHUNK):
                chunk=pcm[offset:offset+CHUNK]
                if mode=='new':await clock.until(origin+(offset+len(chunk))/(2*RATE))
                if not written:stamp('firstwrite')
                await rec.write(chunk);written.extend(chunk);stamp('lastwrite')
            row['actualpcm_sha256']=digest(written);row['actualpcm_samples']=len(written)//2
            await clock.until(end+QUIET)
            text=await rec.finish();stamp('final')
            if not isinstance(text,str) or not text.strip():raise GuardError('empty')
            return text
    task=asyncio.create_task(work())
    def observed(done):
        if not done.cancelled():done.exception()
    task.add_done_callback(observed)
    failure=None;text=None
    try:
        # Pair worker has a tighter outer deadline; this is a second local ceiling.
        done,_=await asyncio.wait({task},timeout=18)
        if not done:raise TimeoutError()
        text=task.result()
    except BaseException as error:
        failure=error;task.cancel()
    finally:
        # One absolute .5s window for reader + original V2Speech release, no renewal.
        if not task.done():await asyncio.wait({task},timeout=.5)
        stamp('release_checked')
        row['readtaskpending']=int(speech.reader is not None and not speech.reader.done())
        row['cleanup_confirmed']=bool(task.done() and not speech.release_failed and speech.last_release and speech.last_release['confirmed'] and row['readtaskpending']==0 and not any(not t.done() for t in speech.release_tasks))
        row['timing_ms']['released']=row['timing_ms']['release_checked'] if row['cleanup_confirmed'] else None
        if task.done() and not task.cancelled():task.exception()
        row['timing_ms']['finish_to_final']=None if 'finish' not in row['timing_ms'] or 'final' not in row['timing_ms'] else round(row['timing_ms']['final']-row['timing_ms']['finish'],3)
        if not row['cleanup_confirmed'] and failure is None:failure=GuardError('cleanup')
        if failure is None and (not row['task_finished'] or row['starts']!=1 or row['finishes']!=1):failure=GuardError('task_incomplete')
        row['terminal']='complete' if failure is None else 'timeout' if isinstance(failure,TimeoutError) else 'quota' if isinstance(failure,SpeechTaskError) and failure.code in {'insufficient_quota','AllocationQuota.FreeTierOnly'} else 'failed'
    if failure is not None:raise failure
    row['text']=text_meta(text)
    return text

async def pair(pcm,report,factory,checkpoint,clock=None):
    texts=[]
    try:
        for mode in ('old','new'):
            row=new_row(mode);report['trials'].append(row);checkpoint()
            text=await trial(mode,pcm,row,factory,clock);texts.append(text);checkpoint()
            # Synthetic reference completeness mismatch stops before new.
            if len(texts)==2:report['comparison']=dict(equal=texts[0]==texts[1],normalizedeq=normalized(texts[0])==normalized(texts[1]))
            if not row['text']['reference_normalizedeq']:raise GuardError('reference_mismatch')
        report['comparison']=dict(equal=texts[0]==texts[1],normalizedeq=normalized(texts[0])==normalized(texts[1]))
        report['terminal']='paired_not_phone_not_quality'
    except BaseException as error:
        report['terminal']='timeout' if isinstance(error,(TimeoutError,asyncio.CancelledError)) else 'stopped'
        report['failure_kind']='quota' if isinstance(error,SpeechTaskError) and error.code in {'insufficient_quota','AllocationQuota.FreeTierOnly'} else 'fixed_failure'
    finally:
        texts.clear();checkpoint()
    return 0 if report['terminal']=='paired_not_phone_not_quality' else 1

async def execute(out,tool_source):
    disable_core_dumps();source_guard(tool_source);config=load_config();pcm=fixture()
    report=dict(plan(),tool_source=tool_source,tool_sha256=digest(Path(__file__).read_bytes()),terminal='in_progress',trials=[],calls=dict(asr=0,text=0,tts=0,image=0))
    def checkpoint():
        report['calls']['asr']=ledger.calls
        save(out/'result.json',report)
    ledger=Ledger(checkpoint);checkpoint()
    key=read_checked('/etc/little-buddy-v2/dashscope-api-key','provider_key',limit=4097).rstrip('\r\n')
    def factory(row,stamp):return PairSpeech(None,key=key,**config,ledger=ledger,row=row,checkpoint=checkpoint,stamp=stamp)
    async with asyncio.timeout(19):return await pair(pcm,report,factory,checkpoint)

def save(path,value):
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2).encode()+b'\n'
    # Atomic replacement is only inside the exclusively-created private run directory.
    temp=path.with_suffix('.new')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:
        f.write(raw);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)
    directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(directory)
    finally:os.close(directory)

def private_output(path):
    if path.is_symlink() or path.exists():raise GuardError('output_exists')
    path.mkdir(mode=0o700) # parent must already exist; never create a public tree
    if stat.S_IMODE(path.stat().st_mode)!=0o700:raise GuardError('private_directory')

def group_identity(pid='self'):
    raw=Path(f'/proc/{pid}/cgroup').read_text()
    parts=raw.strip().split(':',2)
    if len(parts)!=3 or parts[:2]!=['0',''] or not re.fullmatch(r'/system.slice/little-buddy-build-[0-9a-f-]+\.service',parts[2]):raise GuardError('build_supervisor_required')
    return parts[2]

def process_start(pid):
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]

def supervisor_guard():
    # systemd-run deliberately does not inherit the wrapper's arbitrary lock FD.
    group=group_identity();control=Path('/sys/fs/cgroup')/group.lstrip('/')
    if (control/'memory.max').read_text().strip()!='2147483648' or (control/'memory.swap.max').read_text().strip()!='0':raise GuardError('resource_limit_required')
    directory=Path('/var/lock/little-buddy');lock=directory/'heavy.lock'
    info=directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))!=(0,0,0o755):raise GuardError('lock_directory')
    fd=os.open(lock,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    import fcntl
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))!=(0,0,0o644):raise GuardError('lock_identity')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:pass # Existing external wrapper still owns its lock.
        else:
            fcntl.flock(fd,fcntl.LOCK_UN) # Only our independent probe, never another owner's descriptor.
            raise GuardError('external_lock_not_held')
    finally:os.close(fd)
    return dict(build_cgroup=True,memory_max=2147483648,memory_swap_max=0,heavy_lock_busy=True)

def parent_guard(pid,start):
    if pid!=os.getppid() or process_start(pid)!=start or group_identity(pid)!=group_identity():raise GuardError('parent_binding')
    return True


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--prepare',action='store_true');m.add_argument('--execute',action='store_true');m.add_argument('--admission-smoke',action='store_true')
    p.add_argument('--tool-source');p.add_argument('--output',type=Path);p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    p.add_argument('--parent-pid',type=int,help=argparse.SUPPRESS);p.add_argument('--parent-start',help=argparse.SUPPRESS)
    a=p.parse_args(argv)
    if not(a.prepare or a.execute or a.admission_smoke):print('disabled');return 0
    if not a.tool_source or a.output is None:raise GuardError('admission')
    source_guard(a.tool_source);out=a.output.absolute()
    if a.prepare:
        load_config();pcm=fixture();private_output(out)
        save(out/'prepare.json',dict(plan(),actualpcm_sha256=digest(pcm),actual_calls=0,tool_source=a.tool_source,tool_sha256=digest(Path(__file__).read_bytes())))
        return 0
    admission=supervisor_guard()
    if a.worker:
        parent_guard(a.parent_pid,a.parent_start)
        if out.is_symlink() or stat.S_IMODE(out.stat().st_mode)!=0o700 or (out/'result.json').exists():raise GuardError('one_worker_only')
        if a.admission_smoke:
            save(out/'admission.json',dict(admission,parent_bound=True,calls=dict(asr=0,text=0,tts=0,image=0)));return 0
        return asyncio.run(execute(out,a.tool_source))
    private_output(out)
    child=subprocess.Popen([sys.executable,'-I','-B',str(Path(__file__).resolve()),'--admission-smoke' if a.admission_smoke else '--execute','--worker','--parent-pid',str(os.getpid()),'--parent-start',process_start(os.getpid()),'--tool-source',a.tool_source,'--output',str(out)],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    forced=False
    try:code=child.wait(timeout=20)
    except subprocess.TimeoutExpired:
        forced=True;os.killpg(child.pid,signal.SIGTERM)
        try:code=child.wait(timeout=1)
        except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);code=child.wait(timeout=1)
    if a.admission_smoke:
        try:valid=json.loads((out/'admission.json').read_text())==dict(admission,parent_bound=True,calls=dict(asr=0,text=0,tts=0,image=0))
        except (OSError,ValueError):valid=False
        cleanup=valid;sha=None
    else:
        try:
            raw=(out/'result.json').read_bytes();r=json.loads(raw);sha=digest(raw)
            valid=r['tool_source']==a.tool_source and r['tool_sha256']==digest(Path(__file__).read_bytes()) and r['caps']==plan()['caps'] and 0<=r['calls']['asr']<=2 and r['calls']['text']==r['calls']['tts']==r['calls']['image']==0
            cleanup=bool(r['trials']) and all(t['cleanup_confirmed'] and t['readtaskpending']==0 for t in r['trials'])
        except (OSError,ValueError,KeyError,TypeError):valid=False;cleanup=False;sha=None
    save(out/'supervisor.json',dict(admission,worker_exit=code,forced_exit=forced,artifact_valid=valid,cleanup_confirmed=cleanup and not forced,result_sha256=sha,automatic_retry=False))
    return code or int(forced or not valid or not cleanup)

if __name__=='__main__':
    try:sys.exit(main())
    except BaseException as error:
        if isinstance(error,SystemExit):raise
        print('asr_pair_admission_failed',file=sys.stderr);sys.exit(2)
