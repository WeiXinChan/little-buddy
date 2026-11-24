"""SDK37310 authenticated LOOPBACK virtual mic. Only hash-allowlisted fixtures reach here.
RPC success is transport evidence, never a live AudioRecord/KWS assertion.
"""
import hashlib,json,os,re,subprocess,time,wave,traceback
from pathlib import Path
PROTO_SHA='9a4b0f704b0d4cdda652f89fbd50bb3d54da3d46ec8efe6e8b2a2a135ef10e69'

class InjectionTimingError(RuntimeError):
    def __init__(self,reason,index,late_ms):
        super().__init__('inject pacing deadline')
        self.reason=reason;self.index=index;self.late_ms=late_ms

class InitJournal:
    def __init__(self,path=Path('render/grpc-mic-init-journal.json')):
        self.path=path;self.path.parent.mkdir(parents=True,exist_ok=True)
        self.data=dict(stage='START',events=[]);self.step('START')
    def step(self,stage,**safe_fields):
        self.data['stage']=stage
        self.data['events'].append(dict(stage=stage,monotonic_ns=time.monotonic_ns(),**safe_fields))
        temp=self.path.with_suffix('.json.tmp');temp.write_text(json.dumps(self.data,indent=2));temp.replace(self.path)
    def failed(self,error):
        fields=dict(error_class=re.sub('[^A-Za-z0-9_]','_',type(error).__name__)[:120],source=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(error.__traceback__) if Path(f.filename).name in ('grpc_mic.py','mic_controller.py')][-6:])
        code=getattr(error,'code',None)
        if callable(code):
            name=getattr(code(),'name','UNKNOWN')
            if re.fullmatch('[A-Z_]+',name):fields['rpc_code']=name
        self.data['failure_stage']=self.data['stage'];self.step('FAILED',**fields)

def owned_pid(pid,root_pid):
    seen=set()
    while pid>1 and pid not in seen:
        seen.add(pid)
        try:
            status=Path(f'/proc/{pid}/status').read_text()
            if int(re.search(r'^Uid:\s+(\d+)',status,re.M)[1])!=os.getuid():return False
            if pid==root_pid:return True
            pid=int(re.search(r'^PPid:\s+(\d+)',status,re.M)[1])
        except (OSError,TypeError,ValueError):return False
    return False

def packet_plan(raw,rate,packet,fmt,clock=time.monotonic,sleep=time.sleep,deadline=None):
    """Recheck after sleep and immediately before yield; never renew total deadline."""
    size=rate//50*2;data=raw+bytes(rate*2*300//1000);start=clock()
    cutoff=deadline if deadline is not None else start+len(data)/(rate*2)+.15
    for index,pos in enumerate(range(0,len(data),size)):
        target=start+pos/(rate*2)
        def check():
            current=clock();late=current-target
            if current>=cutoff:raise InjectionTimingError('STREAM_DEADLINE',index,round(late*1000))
            if late>.15:raise InjectionTimingError('PACKET_LATE',index,round(late*1000))
            return current
        current=check()
        if current<target:sleep(min(target-current,cutoff-current))
        check()
        result=packet(format=fmt,timestamp=time.time_ns()//1000,audio=data[pos:pos+size])
        check()
        yield result

class GrpcMic:
    def __init__(self,journal=None):
        self.init=journal or InitJournal()
        try:self._setup()
        except BaseException as error:
            self.init.failed(error)
            if hasattr(self,'channel'):self.channel.close()
            raise RuntimeError('virtual mic setup failed at '+self.init.data['failure_stage']) from None
    def _setup(self):
        self.init.step('IMPORTS')
        import grpc
        import emulator_controller_pb2 as pb
        import emulator_controller_pb2_grpc as services
        from google.protobuf.empty_pb2 import Empty
        self.grpc=grpc;self.pb=pb;self.Empty=Empty
        self.init.step('SDK_READ')
        sdk=Path(os.environ['ANDROID_HOME'])/'emulator'
        props=(sdk/'source.properties').read_text()
        version=re.search(r'Pkg.Revision=([0-9.]+)',props)
        digest=hashlib.sha256((sdk/'lib/emulator_controller.proto').read_bytes()).hexdigest()
        self.init.step('SDK_CHECK',version=version[1] if version else 'UNKNOWN',proto_match=digest==PROTO_SHA)
        assert version and version[1]=='37.3.10' and digest==PROTO_SHA
        self.init.step('PRIVATE_DIRECTORY_READ')
        root=Path(os.environ['XDG_RUNTIME_DIR']);info=root.stat()
        self.init.step('PRIVATE_DIRECTORY_CHECK',root_match=root==Path(os.environ['RUNNER_TEMP'])/'v2-runtime',owner_match=info.st_uid==os.getuid(),mode=info.st_mode&0o777)
        assert root==Path(os.environ['RUNNER_TEMP'])/'v2-runtime' and info.st_uid==os.getuid() and info.st_mode&0o777==0o700
        self.init.step('DESCRIPTOR_SCAN')
        root_pid=int(os.environ['M06_EMULATOR_PID']);configs=[];seen=0;serials=0;ports=0;tokens=0;pids=0
        for f in (root/'avd/running').glob('pid_*.ini'):
            seen+=1
            if f.stat().st_uid!=os.getuid():continue
            match=re.fullmatch(r'pid_(\d+)\.ini',f.name)
            pid_match=bool(match) and owned_pid(int(match[1]),root_pid)
            d=dict(tuple(part.strip() for part in line.split('=',1)) for line in f.read_text().splitlines() if '=' in line)
            serials+=d.get('port.serial')=='5554';ports+=d.get('grpc.port')=='8554';tokens+=bool(d.get('grpc.token'));pids+=pid_match
            if pid_match and d.get('port.serial')=='5554' and d.get('grpc.port')=='8554' and d.get('grpc.token'):configs.append(d)
        self.init.step('DESCRIPTOR_CHECK',seen=seen,serial_matches=serials,port_matches=ports,token_present_count=tokens,owned_pid_matches=pids,selected=len(configs))
        assert len(configs)==1
        token=configs[0]['grpc.token']  # private, own generated credential; never journal values
        self.init.step('LOOPBACK_READ')
        sockets=subprocess.check_output(['ss','-ltnH'],text=True)
        addresses=[s.split()[3] for s in sockets.splitlines() if s.split()[3].endswith(':8554')]
        valid=bool(addresses) and all(a in ('127.0.0.1:8554','[::1]:8554') for a in addresses)
        self.init.step('LOOPBACK_CHECK',listeners=len(addresses),loopback_only=valid)
        assert valid
        self.channel=grpc.insecure_channel('127.0.0.1:8554')
        self.init.step('CHANNEL_READY')
        grpc.channel_ready_future(self.channel).result(timeout=5)
        self.stub=services.EmulatorControllerStub(self.channel);self.auth=(('authorization','Bearer '+token),)
        self.init.step('ANONYMOUS_REQUEST')
        code='OK'
        try:self.stub.injectAudio(iter(()),timeout=3)
        except grpc.RpcError as error:code=error.code().name
        self.init.step('ANONYMOUS_CHECK',rpc_code=code)
        assert code=='UNAUTHENTICATED'
        self.init.step('AUTHENTICATED_STATUS_REQUEST')
        status=self.stub.getStatus(Empty(),metadata=self.auth,timeout=3)
        version=re.search(r'\d+\.\d+\.\d+(?:\.\d+)?',status.version)
        self.init.step('AUTHENTICATED_STATUS_CHECK',version=version[0] if version else 'UNKNOWN')
        assert version and version[0].startswith('37.3.10')
        self.init.step('HOST_MIC_DISABLE')
        self.stub.setMicrophoneState(pb.MicrophoneState(realAudioEnabled=False),metadata=self.auth,timeout=3)
        self.init.step('HOST_MIC_READ')
        state=self.stub.getMicrophoneState(Empty(),metadata=self.auth,timeout=3)
        self.init.step('HOST_MIC_CHECK',real_audio_enabled=bool(state.realAudioEnabled))
        assert not state.realAudioEnabled
        self.init.step('READY',loopback=True,anonymous_denied=True,host_mic=False)
        Path('render/grpc-mic-ready.json').write_text(json.dumps(dict(version=version[0],proto_sha256=PROTO_SHA,authenticated=True,loopback=True,host_mic=False)))
    def play(self,path,metadata):
        target=Path('render')/('mic-grpc-'+metadata['nonce']+'.json')
        row=dict(metadata,backend='EmulatorController.injectAudio',proto_sha256=PROTO_SHA,stages=[])
        def save(stage,**fields):
            row.update(fields);row['stage']=stage;row['stages'].append(dict(stage=stage,unix_ns=time.time_ns(),monotonic_ns=time.monotonic_ns()))
            target.write_text(json.dumps(row,indent=2))
        save('before_fixture')
        count=0;generator_failure=None
        try:
            assert hashlib.sha256(path.read_bytes()).hexdigest()==metadata['sha256']
            with wave.open(str(path)) as wav:
                rate=wav.getframerate();assert wav.getnchannels()==1 and wav.getsampwidth()==2 and 8000<=rate<=48000
                raw=wav.readframes(wav.getnframes())
            assert len(raw)<=rate*2*16,'bounded allowlisted fixture'
            self.stub.setMicrophoneState(self.pb.MicrophoneState(realAudioEnabled=False),metadata=self.auth,timeout=3)
            assert not self.stub.getMicrophoneState(self.Empty(),metadata=self.auth,timeout=3).realAudioEnabled
            fmt=self.pb.AudioFormat(samplingRate=rate,channels=self.pb.AudioFormat.Mono,format=self.pb.AudioFormat.AUD_FMT_S16,mode=self.pb.AudioFormat.MODE_UNSPECIFIED)
            save('inject_started',rate=rate,channels=1,sample_format='s16le',source_samples=len(raw)//2,drain_ms=300,packet_ms=20,mode='MODE_UNSPECIFIED',host_mic=False)
            seconds=len(raw)/(rate*2)+3;deadline=time.monotonic()+seconds
            def packets():
                nonlocal count,generator_failure
                try:
                    for p in packet_plan(raw,rate,self.pb.AudioPacket,fmt,deadline=deadline):count+=1;yield p
                except InjectionTimingError as error:
                    generator_failure=dict(reason=error.reason,index=error.index,late_ms=error.late_ms)
                    raise
            self.stub.injectAudio(packets(),metadata=self.auth,timeout=seconds)
            save('inject_completed',rpc_code='OK',packets=count,playback_exit=0)
            return row
        except self.grpc.RpcError as e:
            save('rpc_failed',rpc_code=e.code().name,packets=count,generator_failure=generator_failure)  # no message/details/token
            raise RuntimeError('virtual mic RPC '+e.code().name) from None
        except Exception as e:
            save('failed',error=type(e).__name__);raise
    def close(self):self.channel.close()
