"""SDK37310 authenticated LOOPBACK virtual mic. Only hash-allowlisted fixtures reach here.
RPC success is transport evidence, never a live AudioRecord/KWS assertion.
"""
import hashlib,json,os,re,subprocess,time,wave
from pathlib import Path
PROTO_SHA='9a4b0f704b0d4cdda652f89fbd50bb3d54da3d46ec8efe6e8b2a2a135ef10e69'

def packet_plan(raw,rate,packet,fmt,clock=time.monotonic,sleep=time.sleep):
    """20ms paced packets, non-real-time buffer mode;300ms explicit silence drain."""
    size=rate//50*2
    data=raw+bytes(rate*2*300//1000)
    start=clock()
    for pos in range(0,len(data),size):
        target=start+pos/(rate*2)
        late=clock()-target
        if late>.15:raise RuntimeError('inject pacing missed bounded deadline')
        if late<0:sleep(-late)
        yield packet(format=fmt,timestamp=time.time_ns()//1000,audio=data[pos:pos+size])

class GrpcMic:
    def __init__(self):
        import grpc
        import emulator_controller_pb2 as pb
        import emulator_controller_pb2_grpc as services
        from google.protobuf.empty_pb2 import Empty
        self.grpc=grpc;self.pb=pb;self.Empty=Empty
        sdk=Path(os.environ['ANDROID_HOME'])/'emulator'
        assert 'Pkg.Revision=37.3.10' in (sdk/'source.properties').read_text()
        assert hashlib.sha256((sdk/'lib/emulator_controller.proto').read_bytes()).hexdigest()==PROTO_SHA
        root=Path(os.environ['XDG_RUNTIME_DIR']);assert root==Path(os.environ['RUNNER_TEMP'])/'v2-runtime'
        assert root.stat().st_uid==os.getuid() and root.stat().st_mode&0o777==0o700
        configs=[]
        for f in (root/'avd/running').glob('pid_*.ini'):
            if f.stat().st_uid!=os.getuid():continue
            d=dict(tuple(part.strip() for part in line.split('=',1)) for line in f.read_text().splitlines() if '=' in line)
            if d.get('port.serial')=='5554' and d.get('grpc.port')=='8554' and d.get('grpc.token'):configs.append(d)
        assert len(configs)==1,'one owned AVD auth descriptor required'
        token=configs[0]['grpc.token']  # own generated AVD credential, never logged/exported
        sockets=subprocess.check_output(['ss','-ltnH'],text=True)
        addresses=[s.split()[3] for s in sockets.splitlines() if s.split()[3].endswith(':8554')]
        assert addresses and all(a in ('127.0.0.1:8554','[::1]:8554') for a in addresses),'loopback only'
        self.channel=grpc.insecure_channel('127.0.0.1:8554')
        grpc.channel_ready_future(self.channel).result(timeout=5)
        self.stub=services.EmulatorControllerStub(self.channel)
        self.auth=(('authorization','Bearer '+token),)
        try:self.stub.injectAudio(iter(()),timeout=3)
        except grpc.RpcError as e:assert e.code()==grpc.StatusCode.UNAUTHENTICATED,'anonymous must be denied'
        else:raise RuntimeError('missing gRPC authentication enforcement')
        status=self.stub.getStatus(Empty(),metadata=self.auth,timeout=3)
        assert '37.3.10' in status.version
        self.stub.setMicrophoneState(pb.MicrophoneState(realAudioEnabled=False),metadata=self.auth,timeout=3)
        assert not self.stub.getMicrophoneState(Empty(),metadata=self.auth,timeout=3).realAudioEnabled
        Path('render/grpc-mic-ready.json').write_text(json.dumps(dict(version=status.version,proto_sha256=PROTO_SHA,auth='Bearer enforced; token redacted',loopback=True,host_mic=False)))
    def play(self,path,metadata):
        target=Path('render')/('mic-grpc-'+metadata['nonce']+'.json')
        row=dict(metadata,backend='EmulatorController.injectAudio',proto_sha256=PROTO_SHA,stages=[])
        def save(stage,**fields):
            row.update(fields);row['stage']=stage;row['stages'].append(dict(stage=stage,unix_ns=time.time_ns(),monotonic_ns=time.monotonic_ns()))
            target.write_text(json.dumps(row,indent=2))
        save('before_fixture')
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
            count=0
            def packets():
                nonlocal count
                for p in packet_plan(raw,rate,self.pb.AudioPacket,fmt):count+=1;yield p
            self.stub.injectAudio(packets(),metadata=self.auth,timeout=len(raw)/(rate*2)+3)
            save('inject_completed',rpc_code='OK',packets=count,playback_exit=0)
            return row
        except self.grpc.RpcError as e:
            save('rpc_failed',rpc_code=e.code().name)  # no message/details/token
            raise RuntimeError('virtual mic RPC '+e.code().name) from None
        except Exception as e:
            save('failed',error=type(e).__name__);raise
    def close(self):self.channel.close()
