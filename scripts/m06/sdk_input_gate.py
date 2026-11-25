"""GHA private-null-Pulse only. No producer-thread RPC or host microphone access.
Only whitelisted audio settings are retained; never dump command/environment data.
"""
import json
import traceback
from collections import Counter
import os
from pathlib import Path
import re
import stat
import subprocess
import threading
import time

class IsolationError(RuntimeError):
    def __init__(self,code):
        super().__init__(code);self.reason=code if re.fullmatch('[A-Z_]{1,64}',code) else 'UNKNOWN'
class GateError(RuntimeError): pass


def nul_fields(path):
    # Stream /proc entries and discard unknown fields without persisting a raw dump.
    with path.open('rb') as f:
        item=bytearray()
        while byte:=f.read(1):
            if byte==b'\0':
                yield bytes(item).decode('utf-8','replace');item.clear()
            else:
                item.extend(byte)
                if len(item)>16384: raise IsolationError('PROC_FIELD_BOUND')
        if item: yield bytes(item).decode('utf-8','replace')


def owner(pid,uid):
    try:
        s=Path(f'/proc/{pid}/status').read_text()
        return int(re.search(r'^Uid:\s+(\d+)',s,re.M)[1])==uid
    except (OSError,ValueError,TypeError): return False


def descendant(pid,root,uid):
    seen=set()
    while pid>1 and pid not in seen:
        seen.add(pid)
        if not owner(pid,uid): return False
        if pid==root: return True
        s=Path(f'/proc/{pid}/status').read_text();pid=int(re.search(r'^PPid:\s+(\d+)',s,re.M)[1])
    return False


def safe_failure(error):
    return dict(error_class=type(error).__name__,isolation_reason=getattr(error,'reason',None),source=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(error.__traceback__) if Path(f.filename).name in ('sdk_input_gate.py','grpc_mic.py')][-6:])


def module_ids(modules,short_text):
    # PulseAudio 16.1 JSON has no module index. Short TEXT carries the ID.
    if not isinstance(modules,list) or len(modules)!=3:raise IsolationError('MODULE_SCHEMA')
    allowed={'module-native-protocol-unix','module-null-sink'}
    if any(not isinstance(m,dict) or m.get('name') not in allowed for m in modules):raise IsolationError('NON_NULL_MODULE')
    rows=[]
    for line in short_text.splitlines():
        fields=line.split('\t',2)  # Discard arguments; never log them.
        if len(fields)<2 or not re.fullmatch('[0-9]{1,10}',fields[0]) or fields[1] not in allowed:raise IsolationError('MODULE_ID_SCHEMA')
        rows.append(dict(index=int(fields[0]),name=fields[1]))
    if len(rows)!=3 or len({r['index'] for r in rows})!=3 or Counter(r['name'] for r in rows)!=Counter(m['name'] for m in modules):raise IsolationError('MODULE_ID_MISMATCH')
    return rows


def topology_projection(sources,sinks,modules,clients,outputs):
    names={'v2_playback','m06_input','v2_playback.monitor','m06_input.monitor'}
    def number(v):return int(v) if re.fullmatch('[0-9]{1,10}',str(v)) else None
    def nodes(rows):
        return [{k:(number(v) if k in ('index','owner_module') else v if (v in names or (k=='driver' and v=='module-null-sink.c')) else 'OTHER') for k,v in r.items() if k in ('index','name','driver','owner_module','monitor_source')} for r in rows[:8]]
    return dict(sources=nodes(sources),sinks=nodes(sinks),modules=[dict(index=number(m.get('index')),name=m.get('name') if m.get('name') in ('module-null-sink','module-native-protocol-unix') else 'OTHER') for m in modules[:8]],clients=[dict(index=number(c.get('index')),pid=number(c.get('properties',{}).get('application.process.id'))) for c in clients[:16]],outputs=[dict(index=number(o.get('index')),client=number(o.get('client')),source=number(o.get('source')),corked=o.get('corked') if isinstance(o.get('corked'),bool) else None) for o in outputs[:16]])


def topology(sources,sinks,modules,clients,outputs,owned_qemu):
    expected={'v2_playback','m06_input'}
    if len(sources)!=2 or len(sinks)!=2 or {s['name'] for s in sinks}!=expected: raise IsolationError('NON_PRIVATE_TOPOLOGY')
    mods={str(m['index']):m for m in modules}
    if sorted(m['name'] for m in modules)!=['module-native-protocol-unix','module-null-sink','module-null-sink']: raise IsolationError('NON_NULL_MODULE')
    sink_names={s['name']:s for s in sinks}
    if len({str(s['index']) for s in sinks})!=2 or len({str(s['index']) for s in sources})!=2 or {s['name'] for s in sources}!={n+'.monitor' for n in expected}:raise IsolationError('DUPLICATE_OR_UNKNOWN_MONITOR')
    if len({str(s['owner_module']) for s in sinks})!=2:raise IsolationError('SHARED_SINK_OWNER')
    for sink in sinks:
        m=mods.get(str(sink['owner_module']),{})
        if sink.get('driver')!='module-null-sink.c' or m.get('name')!='module-null-sink': raise IsolationError('NON_NULL_SINK')
    for source in sources:
        sink=sink_names.get(source.get('monitor_source'), {})
        if not sink:raise IsolationError('SOURCE_UNKNOWN_SINK')
        if source['name']!=sink['name']+'.monitor' or sink.get('monitor_source')!=source['name']:raise IsolationError('MONITOR_NAME_MISMATCH')
        if source.get('driver')!='module-null-sink.c':raise IsolationError('MONITOR_DRIVER_MISMATCH')
        if str(source['owner_module'])!=str(sink['owner_module']):raise IsolationError('MONITOR_OWNER_MISMATCH')
    qclients={str(c['index']):int(c.get('properties',{}).get('application.process.id','0')) for c in clients}
    qclients={key:pid for key,pid in qclients.items() if owned_qemu(pid)}
    if not qclients: raise IsolationError('NO_OWNED_QEMU_CLIENT')
    source_ids={str(s['index']):s['name'] for s in sources}
    bindings=[]
    for output in outputs:
        if str(output.get('client')) in qclients:
            name=source_ids.get(str(output['source']))
            if name!='m06_input.monitor': raise IsolationError('WRONG_QEMU_INPUT')
            bindings.append(dict(index=output['index'],source=name,corked=output.get('corked')))
    return dict(sources=sorted(s['name'] for s in sources),null_sinks=sorted(expected),
                qemu_pids=sorted(set(qclients.values())),qemu_source_outputs=bindings,
                source_output_present=bool(bindings))


class PrivatePulse:
    def __init__(self,env=None):
        self.env=dict(os.environ if env is None else env);self.uid=os.getuid()
        if any(self.env.get(k)!=v for k,v in {'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','BUDDY_SYNTHETIC_AVD_PROBE':'1','M06_SDK_INPUT_GATE':'1','ANDROID_SERIAL':'emulator-5554'}.items()): raise IsolationError('NOT_OWNED_GHA_AVD')
        tmp=Path(self.env['RUNNER_TEMP']).resolve();self.directory=tmp/'v2-avd';self.socket=self.directory/'pulse.sock'
        self.server='unix:'+str(self.socket)
        self.root=int(self.env['M06_EMULATOR_PID']);self.pulse=int(self.env['M06_PULSE_PID'])
        for p in (self.directory,tmp/'v2-runtime'):
            s=p.stat()
            if p.is_symlink() or s.st_uid!=self.uid or stat.S_IMODE(s.st_mode)!=0o700: raise IsolationError('PRIVATE_DIRECTORY')
        if self.env.get('PULSE_SERVER')!=self.server: raise IsolationError('WRONG_PRIVATE_SERVER')

    def pactl(self,kind):
        # Isolated inherited PULSE_SERVER, output capped by the existing owned-child reader.
        from native_input_metadata import bounded
        raw,info=bounded(['pactl','-f','json','list',kind],limit=65536,seconds=.4)
        if info['status']!='AVAILABLE': raise IsolationError('PULSE_QUERY_UNAVAILABLE')
        return json.loads(raw)

    def module_summary(self,modules):
        from native_input_metadata import bounded
        raw,info=bounded(['pactl','list','short','modules'],limit=16384,seconds=.4)
        if info['status']!='AVAILABLE':raise IsolationError('MODULE_IDS_UNAVAILABLE')
        result=module_ids(modules,raw.decode('utf-8','strict'))
        # Fixed keys/type-only schema; no arguments/properties/unknown values.
        summary=dict(count=len(modules),fields={k:sorted({type(m[k]).__name__ for m in modules if k in m}) for k in ('index','name','argument','usage_counter','properties')},ids=result)
        self.schema=summary
        return result

    def verify(self):
        if not owner(self.pulse,self.uid) or not owner(self.root,self.uid): raise IsolationError('OWNER_CHANGED')
        if Path(f'/proc/{self.pulse}/exe').resolve().name!='pulseaudio': raise IsolationError('PULSE_EXECUTABLE')
        if Path(f'/proc/{self.root}/exe').resolve().name not in ('emulator','qemu-system-x86_64'):raise IsolationError('QEMU_EXECUTABLE')
        args=nul_fields(Path(f'/proc/{self.pulse}/cmdline'));no_default=False;configuration=False
        for a in args:
            if a=='-n': no_default=True
            if a=='-F': configuration=next(args,'')==str(self.directory/'pulse.pa')
        if not no_default or not configuration: raise IsolationError('PULSE_NOT_PRIVATE_N')
        inodes=set()
        with Path('/proc/net/unix').open() as net:
            for line in net:
                fields=line.split()
                if len(fields)>=8 and fields[-1]==str(self.socket):inodes.add(fields[6])
        linked=False
        for fd in Path(f'/proc/{self.pulse}/fd').iterdir():
            try:
                m=re.fullmatch(r'socket:\[([0-9]+)\]',os.readlink(fd))
                if m and m[1] in inodes:linked=True
            except OSError:pass
        if not linked:raise IsolationError('PULSE_SOCKET_NOT_OWNED')
        s=self.socket.stat()
        if not stat.S_ISSOCK(s.st_mode) or s.st_uid!=self.uid: raise IsolationError('PRIVATE_SOCKET')
        sources=self.pactl('sources');sinks=self.pactl('sinks');modules=self.module_summary(self.pactl('modules'));clients=self.pactl('clients');outputs=self.pactl('source-outputs')
        self.topology_snapshot=topology_projection(sources,sinks,modules,clients,outputs)
        row=topology(sources,sinks,modules,clients,outputs,lambda p:descendant(p,self.root,self.uid))
        row['module_schema']=self.schema
        row['topology_snapshot']=self.topology_snapshot
        audio={}
        expected={'PULSE_SERVER':self.server,'QEMU_PA_SERVER':self.server,'PULSE_SOURCE':'m06_input.monitor','QEMU_PA_SOURCE':'m06_input.monitor','PULSE_SINK':'v2_playback','QEMU_PA_SINK':'v2_playback'}
        for pid in row['qemu_pids']:
            if Path(f'/proc/{pid}/exe').resolve().name not in ('emulator','qemu-system-x86_64'):raise IsolationError('QEMU_CLIENT_EXECUTABLE')
            fields={}
            for entry in nul_fields(Path(f'/proc/{pid}/environ')):
                key,sep,value=entry.partition('=')
                if key in expected:
                    if not sep or value!=expected[key]: raise IsolationError('QEMU_AUDIO_ENV_MISMATCH')
                    fields[key]=value
                elif key in ('QEMU_AUDIO_DRV','QEMU_AUDIO_IN_DRV','QEMU_AUDIO_OUT_DRV'):
                    if value not in ('pa','pulseaudio'): raise IsolationError('QEMU_NON_PULSE_DRIVER')
                    fields[key]=value
            if not all(k in fields for k in expected): raise IsolationError('QEMU_AUDIO_ENV_MISSING')
            flags={};args=nul_fields(Path(f'/proc/{pid}/cmdline'))
            for a in args:
                if a in ('-audio','-audio-in','-audio-out','-audiodev'):
                    value=next(args,'');backend=value.split(',',1)[0]
                    if backend not in ('pa','pulseaudio'): raise IsolationError('NON_PULSE_AUDIO_ARGUMENT')
                    safe=dict(backend=backend)
                    for option in value.split(',')[1:]:
                        key,eq,v=option.partition('=')
                        if not eq:raise IsolationError('AUDIO_OPTION_UNKNOWN')
                        if key=='server':
                            if v!=self.server:raise IsolationError('AUDIO_OPTION_SERVER')
                        elif key=='id':
                            if not re.fullmatch('[A-Za-z0-9_]{1,32}',v):raise IsolationError('AUDIO_OPTION_ID')
                        elif key in ('in.name','in.dev'):
                            if v!='m06_input.monitor':raise IsolationError('AUDIO_OPTION_INPUT')
                        elif key in ('out.name','out.dev'):
                            if v!='v2_playback':raise IsolationError('AUDIO_OPTION_OUTPUT')
                        elif key in ('in.buffer-length','out.buffer-length','in.latency','out.latency','timer-period'):
                            if not re.fullmatch('[0-9]{1,7}',v):raise IsolationError('AUDIO_OPTION_NUMBER')
                        else:raise IsolationError('AUDIO_OPTION_UNKNOWN')
                        safe[key]=v
                    flags[a]=safe  # Only whitelisted typed audio options.
                elif a in ('-no-audio','-noaudio'): raise IsolationError('AUDIO_DISABLED')
            audio[str(pid)]=dict(environment=fields,audio_backend_arguments=flags)
        row.update(private_pulse_n=True,private_unix=True,audio=audio)
        return row


class InputGateObserver:
    """At most one false->true per stream, bounded to this inject call; finally false."""
    def __init__(self,read,write,prove,path,ready_delay=.12,context=None):
        self.read=read;self.write=write;self.prove=prove;self.path=path
        self.started=threading.Event();self.stop=threading.Event();self.ready_delay=ready_delay
        self.row=dict(context or {},restored_false=False,observer_stopped=False,enabled_during_stream=False,scope='private GHA null-monitor SDK gate experiment; not consumer proof',events=[],set_true_count=0)
        self.decision_made=False
        self.failure=None;self.thread=threading.Thread(target=self._sample,name='owned-sdk-gate')
    def save(self,kind,**fields):
        self.row['events'].append(dict(event=kind,monotonic_ns=time.monotonic_ns(),**fields))
        self.path.write_text(json.dumps(self.row,indent=2))
    def begin(self):
        self.save('ISOLATION_BEGIN')
        try:
            self.row['isolation_before']=self.prove()
        except Exception as error:
            self.save('ISOLATION_FAILED',topology_snapshot=getattr(getattr(self.prove,'__self__',None),'topology_snapshot',None),**safe_failure(error));raise
        self.thread.start()
    def first_packet(self): self.started.set()  # Producer does no RPC/proof/disk work here.
    def _sample(self):
        try:
            while not self.started.wait(.05):
                if self.stop.is_set():return
            if self.stop.wait(self.ready_delay):return
            while not self.stop.is_set():
                value=bool(self.read());self.save('STREAM_GATE_READ',enabled=value)
                if value:self.row['enabled_during_stream']=True
                first=not self.decision_made
                self.decision_made=True
                if first and not value:
                    proof=self.prove()
                    if self.stop.is_set():return
                    self.row['isolation_at_enable']=proof
                    self.write(True);self.row['set_true_count']=1
                    actual=bool(self.read());self.save('STREAM_GATE_SET_TRUE',enabled=actual)
                    if not actual:raise GateError('ENABLE_NOT_OBSERVED')
                    self.row['enabled_during_stream']=True
                elif not value:self.save('GATE_FALSE_OBSERVED_NO_RETRY',enabled=False)
                self.stop.wait(.2)
        except Exception as error:
            self.failure=type(error).__name__;self.save('OBSERVER_FAILED',**safe_failure(error))
    def finish(self):
        self.stop.set()
        if self.thread.ident is not None:self.thread.join(20)
        if self.thread.is_alive():raise GateError('OBSERVER_DID_NOT_RETIRE')
        # Always stop/join observer before restoration. Never enable in cleanup.
        self.row['observer_stopped']=True
        try:
            self.write(False);actual=bool(self.read())
            self.row['restored_false']=not actual
            self.save('RESTORED_FALSE',enabled=actual,observer_alive=False)
        except Exception as error:
            self.save('RESTORE_FAILED',error_class=type(error).__name__,observer_alive=False)
            raise GateError('RESTORE_FAILED') from None
        if actual or self.failure or not self.row['enabled_during_stream']:raise GateError('RESTORE_OR_OBSERVER_FAILED')
