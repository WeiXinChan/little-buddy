"""One opt-in isolated TLS diagnostic. No phone, no fallback, no body/PCM export."""
import argparse,asyncio,base64,hashlib,json,os,secrets,signal,ssl,subprocess,sys,tempfile,time
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from backend.v2 import timing
from backend.v2.companion import UnifiedProviders,CompanionPolicy
from backend.v2.server import voice_server
from backend.v2.voice import VoicePeer
from websockets.asyncio.client import connect
AUDIO=Path('/home/ubuntu/tech/v2-delivery/performance-aiff-private/ordinary-introduction.aiff')
AUDIO_SHA='1b7d418ac0550d7cb4e9a6f5c947bf72825caa464b616d6279c678dd3ab3aaad'
MODELS=dict(llm='deepseek-v4.1-flash-1017',asr='fun-asr-realtime',tts='cosyvoice-v3-flash')
class GateError(Exception):pass
class Allowance:
    def __init__(self):self.started=time.monotonic();self.calls=dict(asr=0,text=0,tts=0);self.stages={};self.stopped=False;self.reason=None
    def take(self,kind,stage=None):
        if self.stopped or time.monotonic()-self.started>=45:raise GateError('stopped_or_deadline')
        if kind not in self.calls or self.calls[kind]>={'asr':1,'text':9,'tts':4}[kind]:self.stopped=True;self.reason='call_limit';raise GateError('call_limit')
        if kind=='text':
            if stage not in {'endpoint','plan','facts','review'}:self.stopped=True;self.reason='undeclared_stage';raise GateError('undeclared_stage')
            if self.stages.get(stage,0)>={'endpoint':2,'plan':2,'facts':2,'review':5}[stage]:self.stopped=True;self.reason='stage_limit';raise GateError('stage_limit')
            self.stages[stage]=self.stages.get(stage,0)+1
        self.calls[kind]+=1
    def fail(self):self.stopped=True;self.reason=self.reason or 'supplier_or_protocol_failure'
class NoImages:
    def __init__(self,meter):self.meter=meter
    def catalogue(self):return []
    def candidate(self,request):return None
    async def prepare(self,*a,**kw):self.meter.reason='image_not_admitted';self.meter.fail();raise GateError('image_not_admitted')
    def accepts(self,*a):return False

def forbid_images(providers,meter):
    images=NoImages(meter);providers.images=images;providers.dynamic_images=None
    for name in ('prepare_visual','prepare_generated_image','prepare_dynamic_visual'):
        setattr(providers,name,images.prepare)

class MeterModel:
    def __init__(self,inner,meter):self.inner=inner;self.meter=meter;self.model=MODELS['llm']
    async def complete(self,instruction,data,*,schema=None):
        props=(schema or {}).get('properties',{})
        stage='endpoint' if 'completion' in props else 'plan' if 'mode' in props else 'facts' if 'facts' in props else 'review' if 'allow' in props else 'other'
        self.meter.take('text',stage)
        try:return await self.inner.complete(instruction,data,schema=schema)
        except BaseException:self.meter.fail();raise
class MeterSpeech:
    def __init__(self,inner,meter):self.inner=inner;self.meter=meter;self.empty=None;self.conforms=None
    @asynccontextmanager
    async def recognize(self,rate):
        self.meter.take('asr');owner=self
        try:
            async with self.inner.recognize(rate) as rec:
                class Recognition:
                    async def write(self,pcm):await rec.write(pcm)
                    async def finish(self):
                        text=await rec.finish()
                        import re
                        normalize=lambda s:re.sub(r'[\s，。！？、,.!?]','',s)
                        owner.empty=not bool(text.strip());owner.conforms=normalize(text)==normalize('你好，请用一句话介绍你自己')
                        if owner.empty or not owner.conforms:owner.meter.reason='asr_fixture_mismatch';owner.meter.fail();raise GateError('asr_fixture_mismatch')
                        return text
                yield Recognition()
        except BaseException:self.meter.fail();raise
    @asynccontextmanager
    async def synthesize(self,text,rate):
        self.meter.take('tts')
        try:
            async with self.inner.synthesize(text,rate) as source:yield source
        except BaseException:self.meter.fail();raise

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,ensure_ascii=False,indent=2)

def source_guard(source):
    if len(source)!=40 or subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()!=source:raise GateError('source_pin')
    if subprocess.run(['git','diff','--quiet','HEAD','--','backend','scripts/v2_stage_probe.py'],cwd=ROOT).returncode:raise GateError('dirty_source')

def fixture():
    if AUDIO.is_symlink() or hashlib.sha256(AUDIO.read_bytes()).hexdigest()!=AUDIO_SHA:raise GateError('fixture_hash')
    meta=json.loads((AUDIO.parent/'metadata.json').read_text())
    if meta['sha256']!=AUDIO_SHA or meta['sample_rate_hz']!=22050 or meta['sample_count']!=68097 or meta['regenerated'] is not True:raise GateError('fixture_metadata')
    pcm=subprocess.check_output(['ffmpeg','-nostdin','-v','error','-i',str(AUDIO),'-ac','1','-ar','16000','-f','s16le','pipe:1'],stderr=subprocess.DEVNULL,timeout=8)
    if not 49000<=len(pcm)//2<=50000 or len(pcm)%2:raise GateError('fixture_pcm')
    return pcm,dict(source_sha256=AUDIO_SHA,regenerated=True,source_rate=22050,source_samples=68097,pcm_rate=16000,pcm_samples=len(pcm)//2,pcm_sha256=hashlib.sha256(pcm).hexdigest(),realtime=True)

async def exercise(providers,meter,pcm,tls,client_tls,token,trace):
    peer=None;finished=asyncio.Event();client_rows=[];chunks=acks=0;audio_bytes=0;terminal='not_started';output_started=False
    class Peer(VoicePeer):
        def __init__(self,*a,**kw):
            nonlocal peer
            super().__init__(*a,**kw);peer=self
        async def run(self):
            try:await super().run()
            finally:finished.set()
    from backend.v2 import server as server_module
    with timing.observe(trace),patch.object(server_module,'VoicePeer',Peer):
        async with voice_server('127.0.0.1',0,tls,token,providers,CompanionPolicy()) as server:
            port=server.sockets[0].getsockname()[1]
            async with connect('wss://127.0.0.1:'+str(port)+'/v2/voice',ssl=client_tls,server_hostname='localhost',additional_headers={'Authorization':'Bearer '+token},max_size=16000,max_queue=4) as ws:
                epoch=0;seq=0;write_lock=asyncio.Lock();bound=None
                async def send(kind,**fields):
                    nonlocal seq
                    async with write_lock:
                        await ws.send(json.dumps(dict(v=2,type=kind,epoch=epoch,seq=seq,**fields)));seq+=1
                async def heartbeats():
                    while True:await asyncio.sleep(1);await send('heartbeat')
                hb=asyncio.create_task(heartbeats())
                try:
                    await send('scope');await ws.recv()
                    await send('wake');await send('advance',revision=1)
                    begin=time.monotonic()
                    for offset in range(0,len(pcm),640):
                        target=begin+offset/32000
                        await asyncio.sleep(max(0,target-time.monotonic()))
                        await send('input',pcm=base64.b64encode(pcm[offset:offset+640]).decode(),speech=True,age_ms=0)
                    await asyncio.sleep(max(0,begin+len(pcm)/32000-time.monotonic()))
                    input_end=time.monotonic();client_rows.append(dict(stage='input_finished',ms=round((input_end-trace.started)*1000,3),bytes=len(pcm)))
                    await asyncio.sleep(.3);await send('probe',revision=1)
                    async for raw in ws:
                        e=json.loads(raw);kind=e['type']
                        if kind=='endpoint':
                            if e['completion']!='complete':terminal='endpoint_not_complete';meter.fail();break
                            await asyncio.sleep(max(0,input_end+1-time.monotonic()));await send('seal',revision=1)
                        elif kind=='decision':
                            if e['meaning']!='new_turn':terminal='decision_not_new_turn';meter.fail();break
                            async with write_lock:
                                epoch+=1;seq=0
                                await ws.send(json.dumps(dict(v=2,type='stop',epoch=epoch,seq=seq,intent=e['intent'])));seq+=1
                        elif kind=='open':await send('bind',player='isolated-synthetic')
                        elif kind=='bound':bound=e
                        elif kind=='audio':
                            if not bound:raise GateError('audio_unbound')
                            data=base64.b64decode(e['pcm'],validate=True)
                            if not data or len(data)>4800 or len(data)%2:raise GateError('audio_capacity')
                            chunks+=1;audio_bytes+=len(data)
                            if not output_started:output_started=True;client_rows.append(dict(stage='first_audio_received',ms=round((time.monotonic()-trace.started)*1000,3),bytes=len(data)))
                            await asyncio.sleep(len(data)/48000) # synthetic native playback pace, not acoustic output
                            identity=dict(bound['identity'],sequence=acks)
                            await send('ack',identity=identity,player=bound['player'],stream=bound['stream'],segment=e['segment'],head=e['end']);acks+=1
                        elif kind=='failure':terminal='server_failure';meter.fail();break
                        elif kind=='reply_end':terminal='reply_complete';break
                    await send('end')
                finally:
                    hb.cancel();await asyncio.gather(hb,return_exceptions=True)
            try:await asyncio.wait_for(finished.wait(),1.5)
            except TimeoutError:terminal='cleanup_unconfirmed'
    tasks=set(peer.retired_tasks) if peer else set()
    if peer:tasks|={t for t in (peer.generation,peer.recognition,peer.visual_task) if t is not None}
    pending=sum(not t.done() for t in tasks)
    good=bool(peer and finished.is_set() and peer.closed and not peer.session.active and not peer.quarantined and pending==0 and not peer.session.pending)
    return dict(terminal=terminal,client_stages=client_rows,audio_chunks=chunks,audio_bytes=audio_bytes,synthetic_acks=acks,cleanup=dict(confirmed=good,pending=pending,quarantined=bool(peer and peer.quarantined)),peer_failure=None if not peer else peer.last_failure if hasattr(peer,'last_failure') else None)

async def worker(out,source):
    from backend.v2.runtime import settings,providers,FIELDS
    from backend.dashscope import http_client
    source_guard(source);pcm,media=fixture();meter=Allowance();trace=timing.Trace();result=dict(source=source,models=MODELS,media=media,p12_verified=False,p15_verified=False,layer='synthetic realtime ASR input / real providers / loopback TLS / simulated paced playback ACK; no phone or speaker',quota_live_verified=False,bill_verified=False)
    def progress(row):
        save(out/'progress.json',dict(source=source,trace=trace.report(),calls=dict(meter.calls),stage_calls=dict(meter.stages),terminal='in_progress',cleanup_confirmed=False))
    trace.observer=progress
    try:
        config=settings(environment={},service_env='/etc/little-buddy-v2/service.env')
        if any(config[k]!=v for k,v in MODELS.items()):raise GateError('model_mismatch')
        with tempfile.TemporaryDirectory(prefix='v2-stage-') as temp:
            t=Path(temp);os.chmod(t,0o700)
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost','-keyout',str(t/'key'),'-out',str(t/'cert')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
            os.chmod(t/'key',0o600);os.chmod(t/'cert',0o600)
            tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(t/'cert',t/'key');client_tls=ssl.create_default_context(cafile=str(t/'cert'))
            async with http_client() as http:
                p=providers(http,environment={FIELDS[k]:v for k,v in config.items()},credential_directory='/etc/little-buddy-v2')
                forbid_images(p,meter)
                actual=p.speech;model=p.model;speech=MeterSpeech(actual,meter);p.speech=speech;p.model=MeterModel(model,meter)
                try:
                    async with asyncio.timeout(45):result.update(await exercise(p,meter,pcm,tls,client_tls,secrets.token_hex(24),trace))
                finally:
                    result.update(asr_empty=speech.empty,asr_fixed_case_matches=speech.conforms,model_metrics=model.metrics(),provider_release=dict(failed=actual.release_failed,pending=sum(not t.done() for t in actual.release_tasks),last=actual.last_release))
    except BaseException as e:
        result['terminal']='timeout' if isinstance(e,TimeoutError) else 'failed';result['failure_kind']=type(e).__name__ if type(e).__name__ in {'TimeoutError','GateError','CancelledError'} else 'other'
        result.setdefault('cleanup',dict(confirmed=False,pending=None,quarantined=True));meter.fail()
    finally:
        result.update(image_calls=0,image_review_calls=0,external_image_downloads=0,trace=trace.report(),calls=meter.calls,stage_calls=meter.stages,budget_stop=meter.reason)
        save(out/'result.json',result)
    return 0 if result.get('terminal')=='reply_complete' and result.get('cleanup',{}).get('confirmed') and result.get('provider_release',{}).get('failed') is False else 1

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute',action='store_true');p.add_argument('--source');p.add_argument('--output',type=Path);p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    a=p.parse_args(argv)
    if not a.execute:print('disabled: explicit --execute required');return 0
    if not a.source or a.output is None:raise GateError('admission')
    source_guard(a.source);out=a.output.resolve()
    if not a.worker:
        if out.exists():raise GateError('one_run_output_exists')
        out.mkdir(mode=0o700,parents=True)
        # Must be launched under the reviewed global with-build-lock cgroup.
        if 'little-buddy-build-' not in Path('/proc/self/cgroup').read_text():raise GateError('build_supervisor_required')
        cmd=[sys.executable,'-I','-B',str(Path(__file__).resolve()),'--execute','--source',a.source,'--output',str(out),'--worker']
        child=subprocess.Popen(cmd,start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        forced=False
        try:code=child.wait(timeout=55)
        except subprocess.TimeoutExpired:
            forced=True;os.killpg(child.pid,signal.SIGTERM)
            try:code=child.wait(timeout=2)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);code=child.wait(timeout=2)
        valid=False;cleanup=False
        try:
            r=json.loads((out/'result.json').read_text())
            valid=(r.get('source')==a.source and type(r.get('calls')) is dict and
                   set(r['calls'])=={'asr','text','tts'} and
                   all(type(r['calls'][k]) is int and 0<=r['calls'][k]<=cap for k,cap in {'asr':1,'text':9,'tts':4}.items()) and
                   type(r.get('cleanup',{}).get('confirmed')) is bool and isinstance(r.get('trace',{}).get('records'),list) and len(r['trace']['records'])<=128)
            cleanup=valid and r['cleanup']['confirmed'] and not forced
        except (OSError,ValueError,TypeError,KeyError):pass
        save(out/'supervisor.json',dict(source=a.source,worker_exit=code,forced_exit=forced,artifact_valid=valid,cleanup_confirmed=cleanup,automatic_retry=False,progress_artifact_preserved=(out/'progress.json').exists()))
        return code or (1 if forced or not valid or not cleanup else 0)
    if 'little-buddy-build-' not in Path('/proc/self/cgroup').read_text():raise GateError('build_supervisor_required')
    return asyncio.run(worker(out,a.source))
if __name__=='__main__':
    try:sys.exit(main())
    except BaseException as e:
        if isinstance(e,SystemExit):raise
        print('diagnostic_admission_failed',file=sys.stderr);sys.exit(2)
