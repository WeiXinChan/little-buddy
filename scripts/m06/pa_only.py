"""Synthetic private-null PA-only experiment. Never calls injectAudio."""
import re
import array,hashlib,json,math,os,selectors,subprocess,threading,time,wave
from pathlib import Path
from sdk_input_gate import PrivatePulse,safe_failure

class PaFailure(RuntimeError):
    CODES={'FIXTURE_HASH','FIXTURE_FORMAT','FIXTURE_BOUND','MONITOR_INCOMPLETE','MONITOR_CORRELATION','MONITOR_EOF','MONITOR_WORKER_ALIVE','MONITOR_ERROR_OR_BOUND','MONITOR_PROCESS_EXIT','STREAM_NOT_BOUND','STREAM_ROUTE_OR_FORMAT','NONCE','NONCE_REPLAY','QEMU_INPUT_MISSING','QEMU_INPUT_CORKED','SDK_TRUE_NOT_OBSERVED','SDK_TRUE_LOST','PAPLAY_EXIT','SDK_FALSE_NOT_OBSERVED'}
    def __init__(self,code):
        self.reason=code if code in self.CODES else 'UNKNOWN';super().__init__(self.reason)

def allowlist():
    base=Path('app/src/androidTest/assets/m06-commands');protocol=Path('app/src/androidTest/assets/m06-protocol-v2')
    specs={r['name']:(base/(r['name']+'.wav'),r['sha256'],16000) for r in json.loads((base/'cases.json').read_text())['cases']}
    specs.update({r['name']:(base/(r['name']+'.wav'),r['sha256'],16000) for r in json.loads((base/'provenance.json').read_text())['rows']})
    specs.update({'v2_'+r['name']:(protocol/(r['name']+'.wav'),r['sha256'],16000) for r in json.loads((protocol/'provenance.json').read_text())})
    r=json.loads((protocol/'derived-confirm.json').read_text());specs[r['name']]=(protocol/'confirm_exit_short.wav',r['sha256'],16000)
    main=Path('app/src/main/assets/management')
    specs.update({'prod_'+r['name']:(main/(r['name']+'.wav'),r['sha256'],24000) for r in json.loads((main/'provenance.json').read_text())['rows']})
    return specs

def fixture(path,metadata,specs):
    expected,sha,rate=specs[metadata['name']]
    if path.resolve()!=expected.resolve() or metadata['sha256']!=sha or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise PaFailure('FIXTURE_HASH')
    with wave.open(str(path)) as f:
        if (f.getframerate(),f.getnchannels(),f.getsampwidth())!=(rate,1,2) or rate not in (16000,24000):raise PaFailure('FIXTURE_FORMAT')
        raw=f.readframes(f.getnframes())
    payload=bytes(rate*2*600//1000)+raw+bytes(rate*2*300//1000)
    if len(payload)//2>128000 or len(payload)>rate*2*8:raise PaFailure('FIXTURE_BOUND')
    return rate,raw,payload

def reap(process):
    if process is None:return
    if process.poll() is None:process.terminate()
    try:process.wait(timeout=1)
    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=1)

def pcm(raw):
    a=array.array('h');a.frombytes(raw)
    if os.sys.byteorder!='little':a.byteswap()
    return a

def correlation(a,b):
    if len(a)!=len(b) or not a:return 0
    x=sum(a)/len(a);y=sum(b)/len(b);aa=sum((v-x)**2 for v in a);bb=sum((v-y)**2 for v in b)
    return sum((v-x)*(w-y) for v,w in zip(a,b))/math.sqrt(aa*bb) if aa*bb else 0

def alignment(source,capture,rate):
    src=pcm(source);cap=pcm(capture);step=rate//100
    if len(cap)<len(src) or not any(src):raise PaFailure('MONITOR_INCOMPLETE')
    def envelope(a):return [math.sqrt(sum(v*v for v in a[p:p+step])/len(a[p:p+step])) for p in range(0,len(a)-step+1,step)]
    se=envelope(src);ce=envelope(cap)
    choices=[(correlation(se,ce[n:n+len(se)]),n*step) for n in range(len(ce)-len(se)+1)]
    _,coarse=max(choices)
    sparse=src[::16]
    candidates=[(correlation(sparse,cap[lag:lag+len(src):16]),lag) for lag in range(max(0,coarse-step),min(len(cap)-len(src),coarse+step)+1)]
    _,lag=max(candidates);score=correlation(src,cap[lag:lag+len(src)])
    if score<.98:raise PaFailure('MONITOR_CORRELATION')
    return dict(full_source_samples=len(src),lag_samples=lag,correlation=score,monitor_samples=len(cap))

class RequiredMonitor:
    def __init__(self,rate,path):
        self.rate=rate;self.path=path;self.end=time.monotonic()+8;self.cap=min(128000,rate*8)*2
        self.stop=threading.Event();self.error=None;self.size=0
        self.process=subprocess.Popen(['parec','--device=m06_input.monitor','--raw','--format=s16le','--rate='+str(rate),'--channels=1','--latency-msec=20'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        self.worker=threading.Thread(target=self.read,name='owned-required-pa-monitor')
        try:self.worker.start()
        except BaseException:
            reap(self.process);self.process.stdout.close();raise
    def read(self):
        try:
            with selectors.DefaultSelector() as sel,self.path.open('wb') as f:
                sel.register(self.process.stdout,selectors.EVENT_READ)
                while not self.stop.is_set() and self.size<self.cap and time.monotonic()<self.end:
                    if not sel.select(min(.05,max(0,self.end-time.monotonic()))):continue
                    b=os.read(self.process.stdout.fileno(),min(8192,self.cap-self.size))
                    if not b:
                        if self.stop.is_set():break
                        raise PaFailure('MONITOR_EOF')
                    f.write(b);self.size+=len(b)
        except Exception as e:self.error=type(e).__name__
    def finish(self):
        exceeded=time.monotonic()>=self.end or self.size>=self.cap
        unexpected=self.process.poll() is not None
        self.stop.set();reap(self.process);self.worker.join(1)
        if self.worker.is_alive():raise PaFailure('MONITOR_WORKER_ALIVE')
        self.process.stdout.close()
        if unexpected:raise PaFailure('MONITOR_PROCESS_EXIT')
        if self.error or exceeded:raise PaFailure('MONITOR_ERROR_OR_BOUND')
        return self.path.read_bytes()

def binding(proof,pid,kind,rate):
    clients=proof.pactl('clients');ids={str(c['index']) for c in clients if str(c.get('properties',{}).get('application.process.id'))==str(pid)}
    rows=proof.pactl(kind);matches=[r for r in rows if str(r.get('client')) in ids]
    if len(matches)!=1:raise PaFailure('STREAM_NOT_BOUND')
    row=matches[0];key='source' if kind=='source-outputs' else 'sink';nodes=proof.pactl('sources' if key=='source' else 'sinks')
    names={str(n['index']):n['name'] for n in nodes}
    if names.get(str(row.get(key)))!=('m06_input.monitor' if key=='source' else 'm06_input') or row.get('sample_specification')!=f's16le 1ch {rate}Hz' or row.get('mute') is not False:raise PaFailure('STREAM_ROUTE_OR_FORMAT')
    return dict(index=row['index'],client=row['client'],target=names[str(row[key])],sample_specification=row['sample_specification'],corked=row.get('corked'),mute=False)

class PaOnlyMic:
    def __init__(self,control=None,proof=None,specs=None,directory=Path('render')):
        if control is None:
            from grpc_mic import GrpcMic
            control=GrpcMic(state_only_auth=True)  # authenticated loopback get/status/set only, never play/inject
        self.control=control;self.before_restore=lambda:None;self.used=set()
        try:self.proof=proof or PrivatePulse();self.specs=specs or allowlist();self.directory=directory
        except BaseException:
            control.close();raise
    def close(self):self.control.close()
    def state(self):return bool(self.control.stub.getMicrophoneState(self.control.Empty(),metadata=self.control.auth,timeout=.4).realAudioEnabled)
    def set(self,value):self.control.stub.setMicrophoneState(self.control.pb.MicrophoneState(realAudioEnabled=value),metadata=self.control.auth,timeout=.4)
    def play(self,path,metadata,timing=None):
        self.directory.mkdir(parents=True,exist_ok=True);nonce=metadata['nonce']
        if not re.fullmatch('[a-f0-9-]{36}',nonce):raise PaFailure('NONCE')
        if nonce in self.used:raise PaFailure('NONCE_REPLAY')
        self.used.add(nonce)
        target=self.directory/('mic-pa-'+nonce+'.json')
        row=dict(metadata,backend='private Pulse paplay; no injectAudio',stages=[]);monitor=None;playback=None;payload_path=self.directory/('pa-payload-'+nonce+'.wav');primary=None;cap=None
        def save(stage,**fields):
            row.update(fields);row['stage']=stage;row['stages'].append(dict(stage=stage,monotonic_ns=time.monotonic_ns(),**({'sdk_read':fields['sdk_read']} if 'sdk_read' in fields else {})));target.write_text(json.dumps(row,indent=2))
        def read_point(label):
            value=self.state();save(label,sdk_read=dict(point=label,enabled=value,monotonic_ns=time.monotonic_ns()));return value
        save('FIXTURE_VALIDATE')
        try:
            rate,raw,payload=fixture(path,metadata,self.specs)
            save('ISOLATION',rate=rate,channels=1,sample_format='s16le',source_samples=len(raw)//2,prefix_ms=600,prefix_samples=rate*600//1000,tail_ms=300,payload_samples=len(payload)//2,payload_sha256=hashlib.sha256(payload).hexdigest())
            row['isolation_before']=self.proof.verify()
            if not row['isolation_before']['source_output_present']:raise PaFailure('QEMU_INPUT_MISSING')
            read_point('SDK_BEFORE_ENABLE')
            save('SDK_TRUE');self.set(True)
            if not read_point('SDK_AFTER_ENABLE'):raise PaFailure('SDK_TRUE_NOT_OBSERVED')
            save('SDK_TRUE_OBSERVED',sdk_true=True)
            with wave.open(str(payload_path),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(payload)
            os.chmod(payload_path,0o600)
            save('MONITOR_START');monitor=RequiredMonitor(rate,self.directory/('mic-host-'+nonce+'.s16le'))
            until=time.monotonic()+.8
            while True:
                try:row['monitor_binding']=binding(self.proof,monitor.process.pid,'source-outputs',rate);break
                except PaFailure:
                    if time.monotonic()>=until:raise
                    time.sleep(.01)
            save('PAPLAY_ONCE');playback=subprocess.Popen(['paplay','--device=m06_input',str(payload_path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            until=time.monotonic()+.8
            while True:
                try:row['playback_binding']=binding(self.proof,playback.pid,'sink-inputs',rate);break
                except PaFailure:
                    if playback.poll() is not None or time.monotonic()>=until:raise
                    time.sleep(.01)
            row['isolation_during']=self.proof.verify()
            if not row['isolation_during']['source_output_present']:raise PaFailure('QEMU_INPUT_MISSING')
            if not read_point('SDK_DURING_PLAYBACK'):raise PaFailure('SDK_TRUE_LOST')
            if any(b.get('corked') is not False for b in row['isolation_during']['qemu_source_outputs']):raise PaFailure('QEMU_INPUT_CORKED')
            playback.wait(timeout=max(.001,monitor.end-time.monotonic()-.15))
            if playback.returncode:raise PaFailure('PAPLAY_EXIT')
            time.sleep(min(.1,max(0,monitor.end-time.monotonic())))
            if not read_point('SDK_AFTER_PLAYBACK'):raise PaFailure('SDK_TRUE_LOST')
            save('PLAYBACK_DONE',playback_exit=0)
        except BaseException as e:
            primary=e;save('FAILED',failure_stage=row['stage'],**safe_failure(e));raise
        finally:
            cleanup=None
            try:
                try:reap(playback)
                finally:
                    if monitor:cap=monitor.finish()
                save('OWNED_STOPPED',owned_stopped=True)
            except BaseException as e:cleanup=e;save('CLEANUP_FAILED',**safe_failure(e))
            finally:
                try:self.before_restore()
                except BaseException as e:
                    if cleanup is None:cleanup=e
                    save('OBSERVER_CLEANUP_FAILED',**safe_failure(e))
                try:
                    if primary is None and cleanup is None and not read_point('SDK_BEFORE_RESTORE'):raise PaFailure('SDK_TRUE_LOST')
                except BaseException as e:
                    if cleanup is None:cleanup=e
                    save('END_STATE_FAILED',**safe_failure(e))
                try:
                    self.set(False)
                    if self.state():raise PaFailure('SDK_FALSE_NOT_OBSERVED')
                    save('SDK_FALSE',sdk_restored_false=True)
                except BaseException as e:
                    if cleanup is None:cleanup=e
                    save('RESTORE_FAILED',**safe_failure(e))
                payload_path.unlink(missing_ok=True)
            if cleanup:
                if primary:primary.add_note('PA-only cleanup/restore failed')
                else:raise cleanup
        save('MONITOR_VALIDATE')
        try:row['alignment']=alignment(raw,cap,rate)
        except BaseException as e:
            save('FAILED',failure_stage='MONITOR_VALIDATE',**safe_failure(e));raise
        host=dict(metadata,fixture_sha256=metadata['sha256'],file='mic-host-'+nonce+'.s16le',rate=rate,channels=1,format='s16le',capture_sha256=hashlib.sha256(cap).hexdigest(),samples=len(cap)//2,byte_cap=min(128000,rate*8)*2,wall_limit_s=8)
        (self.directory/('mic-host-'+nonce+'.json')).write_text(json.dumps(host,indent=2))
        save('COMPLETED',monitor_sha256=host['capture_sha256'],transport_complete=True)
        return row
