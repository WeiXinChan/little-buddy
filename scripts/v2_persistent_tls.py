"""Opt-in bounded synthetic TLS stability preparation. No cloud/device factory.

One supervised driver and one persistent production-server process, private IPC.
No forced GC, snapshots of object graphs, completed-peer history or trace.
"""
import argparse,asyncio,base64,hashlib,json,os,secrets,signal,socket,ssl,subprocess,sys,tempfile,time,weakref
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
# Internal -I children use this exact reviewed checkout, never another worktree.
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.v2_tls_soak import (TcpRelay,SyntheticSpeech,SyntheticModel,NetworkMeter,TOKEN,MATRIX,TEXTS,drain,wait_pred)
from scripts.v2_soak import Limits,Allowance,resources
from scripts.v2_tls_retention import heavy_lock,require,Rejected
from backend.v2.server import voice_server
from backend.v2.voice import VoicePeer
from backend.v2.companion import UnifiedProviders,CompanionPolicy
from backend.v2.protocol import CONTRACT
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

SECONDS=180
MAX_BYTES=65536

def scalar_resources():
    r=resources()
    require(all(type(r[k]) is int and r[k]>0 for k in ('backend_rss_bytes','backend_threads','backend_fds','asyncio_tasks')))
    return {k:r[k] for k in ('backend_rss_bytes','backend_threads','backend_fds','asyncio_tasks')}

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

def hex_string(value,size):return type(value) is str and len(value)==size and all(c in '0123456789abcdef' for c in value)

@contextmanager
def internal_authority(args):
    # Reject a direct internal invocation before child I/O. --enable isn't proof.
    require(sys.flags.isolated==1 and args.mode in {'_driver','_service'})
    require(type(args.lock_fd) is int and args.lock_fd>=3 and type(args.supervisor_pid) is int and args.supervisor_pid>1)
    require(type(args.parent_pid) is int and os.getppid()==args.parent_pid and hex_string(args.source,40) and hex_string(args.run_id,32))
    require(args.parent_pid==args.supervisor_pid if args.mode=='_driver' else args.driver_pid==args.parent_pid)
    require(os.getsid(0)==(os.getpid() if args.mode=='_driver' else args.driver_pid))
    info=os.fstat(args.lock_fd)
    # /proc fdinfo describes THIS inherited open-file description's real FLOCK.
    # No new lock file, independent acquisition, or caller-supplied flag can attest it.
    records=Path('/proc/self/fdinfo/'+str(args.lock_fd)).read_text().splitlines()
    held=False
    for line in records:
        fields=line.split()
        if len(fields)!=9 or fields[0]!='lock:' or fields[2:5]!=['FLOCK','ADVISORY','WRITE']:continue
        device=fields[6].split(':')
        if len(device)!=3:continue
        held=(fields[5]==str(args.supervisor_pid) and fields[7:]==['0','EOF'] and
              (int(device[0],16),int(device[1],16),int(device[2]))==(os.major(info.st_dev),os.minor(info.st_dev),info.st_ino))
        if held:break
    require(held)
    parent=Path('/proc/'+str(args.parent_pid)+'/cmdline').read_bytes().split(b'\0')
    expected=b'prepare' if args.mode=='_driver' else b'_driver'
    require(expected in parent and any(v in parent for v in (b'scripts.v2_persistent_tls',b'scripts/v2_persistent_tls.py',str(Path(__file__).resolve()).encode())))
    if args.mode=='_service':require(args.source.encode() in parent and args.run_id.encode() in parent)
    # Re-validates the same inode/root-owned 0644 global lock, retaining the same FD.
    with heavy_lock(args.lock_fd):
        source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).resolve().parents[1],timeout=2,text=True).strip()
        require(source==args.source)
        yield dict(lock_identity=digest([info.st_dev,info.st_ino]),run_digest=digest(args.run_id),source_sha=source)

def closure_proof(peer,raw_socket):
    try:
        waiter=peer.socket.connection_lost_waiter
        from websockets.protocol import State
        return (waiter.done() and not waiter.cancelled() and waiter.exception() is None and
                peer.socket.state is State.CLOSED and peer.socket.transport.is_closing() is True and
                raw_socket is not None and type(raw_socket.fileno()) is int and raw_socket.fileno()==-1)
    except (AttributeError,OSError,ValueError):return False

class Channel:
    def __init__(self,reader,writer):self.reader=reader;self.writer=writer;self.lock=asyncio.Lock()
    async def send(self,value):
        raw=json.dumps(value).encode();require(len(raw)<MAX_BYTES)
        self.writer.write(raw+b'\n');await self.writer.drain()
    async def receive(self):
        raw=await self.reader.readline();require(0<len(raw)<MAX_BYTES)
        value=json.loads(raw);require(type(value) is dict);return value
    async def call(self,op,*,allow_failure=False,**fields):
        async with self.lock:
            async with asyncio.timeout(3):
                await self.send(dict(op=op,**fields));r=await self.receive();require(type(r.get('ok')) is bool and (r['ok'] or allow_failure));return r

async def channel(fd):
    sock=socket.socket(fileno=fd);sock.setblocking(False)
    reader,writer=await asyncio.open_connection(sock=sock,limit=MAX_BYTES)
    return Channel(reader,writer)

class Service:
    def __init__(self):
        self.allowance=Allowance(Limits(duration=SECONDS,interval=1,sample_interval=1,max_attempts=42,model_calls=360,tts_calls=64,tts_characters=8192,allowance_units=424))
        self.speech=SyntheticSpeech(self.allowance);self.model=SyntheticModel();self.meter=NetworkMeter(self.model,self.allowance)
        self.peer=None;self.raw_socket=None;self.session_ref=None;self.constructed=0;self.previous_session=None;self.new_session=False;self.finished=True
        self.retired=set();self.server=None;self.errors=0;self.isolated=False;self.started=time.monotonic()
    def track(self,task):
        self.retired.add(task)
        def done(t):
            if not t.cancelled() and t.exception() is not None:self.errors+=1
            self.retired.discard(t)
        task.add_done_callback(done)
    def handles(self):
        tasks=set(self.retired)
        if self.server:tasks|=set(self.server.handler_tasks)
        if self.peer:
            if self.finished:tasks.add(self.peer.socket.connection_lost_waiter)
            tasks|=set(self.peer.retired_tasks)
            tasks|={t for t in (self.peer.generation,self.peer.recognition,self.peer.visual_task) if t is not None}
        return tasks
    def state(self):
        p=self.peer;public=getattr(p.session,'public',()) if p else ()
        binding=digest([p.session.session,p.session.connection]) if p and hasattr(p.session,'session') and hasattr(p.session,'connection') else None
        return dict(constructed=self.constructed,new_session=self.new_session,finished=self.finished,
                    active=bool(p and p.session.active),quarantined=self.isolated or bool(p and p.quarantined),
                    pending=sum(not t.done() for t in self.handles()),retired=len(self.retired),errors=self.errors,
                    generation=bool(p and p.generation and not p.generation.done()),
                    sequence=p.sequence if p else -1,epoch=p.epoch if p else -1,
                    heard=len(p.session.context().get('heard',())) if p else 0,
                    pending_audio=len(p.session.pending) if p else 0,
                    game=p.session.game.get('mode') if p else None,
                    binding=binding,
                    same_session=bool(p and self.session_ref and self.session_ref() is p.session),
                    played_anchor=digest(public[0]) if public else None,played_count=len(public),
                    state_hash=digest([p.session.head,p.session.context().get('heard',()),p.session.game]) if p else None,
                    allowance=self.allowance.report(),resources=scalar_resources(),elapsed=round(time.monotonic()-self.started,6))
    async def dispatch(self,event):
        op=event.get('op')
        require(not self.isolated or op in {'state','shutdown'})
        if op=='configure':
            require(event.get('text_index') in range(len(TEXTS)) and event.get('fault') in MATRIX)
            await wait_pred(lambda:not self.peer or self.finished or not self.state()['generation'])
            self.speech.text=TEXTS[event['text_index']];self.speech.asr_entered.clear();self.model.plan_entered.clear()
            self.speech.asr_gate.set();self.model.plan_gate.set()
            if event['fault']=='asr_rst':self.speech.asr_gate.clear()
            if event['fault'] in {'plan_rst','pause_resume'}:self.model.plan_gate.clear()
        elif op=='entered':
            require(event.get('stage') in {'asr','plan'})
            await (self.speech.asr_entered if event['stage']=='asr' else self.model.plan_entered).wait()
        elif op=='unblock':self.speech.asr_gate.set();self.model.plan_gate.set()
        elif op=='barrier':
            require(type(event.get('seq')) is int)
            await wait_pred(lambda:self.peer is not None and self.peer.sequence>=event['seq'])
        elif op=='release':
            await wait_pred(lambda:self.finished)
            self.speech.asr_gate.set();self.model.plan_gate.set()
            confirmed,pending,errors=await drain(self.handles,time.monotonic()+.6)
            self.errors+=errors;p=self.peer
            require(p is not None)
            good=(confirmed and not self.errors and not p.quarantined and p.closed and not p.session.active and not p.session.pending and closure_proof(p,self.raw_socket))
            snapshot=self.state();snapshot['cleanup_confirmed']=good;snapshot['transport_closed']=closure_proof(p,self.raw_socket)
            if not good:self.isolated=True;return dict(ok=False,state=snapshot)
            self.peer=None;self.raw_socket=None;self.session_ref=None # only a confirmed completed connection; no diagnostic history
            return dict(ok=True,state=snapshot)
        elif op not in {'state','shutdown'}:raise Rejected('ipc_op')
        return dict(ok=True,state=self.state())

async def serve_child(fd,cert,key,authority):
    ipc=await channel(fd);owner=Service();tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(cert,key)
    class Observed(VoicePeer):
        def __init__(self,*a,**kw):
            require(owner.peer is None and not owner.isolated)
            super().__init__(*a,**kw);owner.peer=self;owner.raw_socket=self.socket.transport.get_extra_info('socket');owner.session_ref=weakref.ref(self.session);owner.constructed+=1;owner.finished=False
            owner.new_session=owner.previous_session!=self.session.session;owner.previous_session=self.session.session
        def track_retired(self,task):owner.track(task);return super().track_retired(task)
        async def run(self):
            try:return await super().run()
            finally:owner.finished=True
    with patch('backend.v2.server.VoicePeer',Observed):
        server=await voice_server('127.0.0.1',0,tls,TOKEN,UnifiedProviders(owner.speech,owner.meter),CompanionPolicy());owner.server=server
        await ipc.send(dict(ok=True,port=server.sockets[0].getsockname()[1],pid=os.getpid(),protocol=CONTRACT,authority=authority))
        try:
            async with asyncio.timeout(SECONDS):
                while True:
                    event=await ipc.receive()
                    try:result=await owner.dispatch(event)
                    except Exception:owner.isolated=True;result=dict(ok=False,code='service_unconfirmed',state=owner.state())
                    await ipc.send(result)
                    if event.get('op')=='shutdown':break
        finally:
            owner.allowance.open=False;server.close()
            if owner.peer:owner.peer.socket.transport.abort()
            waiter=asyncio.create_task(server.wait_closed());await asyncio.wait({waiter},timeout=1)
            ipc.writer.close()
            require(waiter.done() and not waiter.cancelled() and waiter.exception() is None)

class Wire:
    """Existing scope/auth/epoch/bind/ACK wire protocol, no PCM/text reporting."""
    def __init__(self,ws,ipc,fault,old_ack):
        self.ws=ws;self.ipc=ipc;self.fault=fault;self.old_ack=old_ack;self.last_ack=None
        self.epoch=0;self.seq=0;self.revision=0;self.ack_seq=0;self.identity=None;self.send_lock=asyncio.Lock()
        self.scope=asyncio.Event();self.endpoint=asyncio.Event();self.acked=asyncio.Event();self.done=asyncio.Event()
        self.frames=0;self.acks=0;self.turn_acks=0;self.delivered=False;self.control=None;self.old_checked=None;self.first_at=None;self.new_at=time.monotonic()
    async def command(self,kind,**fields):
        async with self.send_lock:
            if kind=='stop':self.epoch+=1;self.seq=0
            seq=self.seq;await self.ws.send(json.dumps(dict(v=2,type=kind,epoch=self.epoch,seq=seq,**fields)));self.seq+=1;return seq
    async def receive(self):
        async for raw in self.ws:
            event=json.loads(raw)
            if event.get('epoch')!=self.epoch:continue
            kind=event['type']
            if kind=='scope':require(event.get('protocol_contract')==CONTRACT and event.get('management_v')==1);self.scope.set()
            elif kind=='endpoint':self.endpoint.set()
            elif kind=='decision':await self.command('stop',intent=event['intent'])
            elif kind=='open':await self.command('bind',player='synthetic-persistent-player')
            elif kind=='bound':self.identity=event['identity'];self.ack_seq=0
            elif kind=='audio':
                self.frames+=1;self.first_at=self.first_at or time.monotonic()
                if self.fault in {'partial_rst','half_open','playback_stop'} and self.turn_acks>=1:continue
                if self.old_ack is not None and self.old_checked is None:
                    before=(await self.ipc.call('state'))['state']['state_hash']
                    seq=await self.command('ack',**self.old_ack)
                    after=(await self.ipc.call('barrier',seq=seq))['state']['state_hash'];self.old_checked=before==after;require(self.old_checked)
                ack=dict(identity=dict(self.identity,sequence=self.ack_seq),player=event['player'],stream=event['stream'],segment=event['segment'],head=event['end'])
                self.ack_seq+=1;self.acks+=1;self.turn_acks+=1;self.last_ack=ack;await self.command('ack',**ack);self.acked.set()
            elif kind=='reply_end':self.delivered=True;self.done.set()
            elif kind=='failure':self.control='failure';self.done.set()
    async def heartbeat(self):
        while True:await self.command('heartbeat');await asyncio.sleep(5)
    async def input(self):
        self.endpoint.clear();self.done.clear();self.acked.clear();self.delivered=False;self.turn_acks=0
        self.revision+=1
        await self.command('advance',revision=self.revision)
        await self.command('input',pcm=base64.b64encode(b'\x01\x00'*320).decode())
        await self.command('probe',revision=self.revision)
    async def seal(self):await self.endpoint.wait();await self.command('seal',revision=self.revision)

class Driver:
    def __init__(self,ipc,tls,port,rounds):
        self.ipc=ipc;self.tls=tls;self.port=port;self.rounds=rounds;self.rows=[];self.checkpoints=[];self.current=None;self.old_ack=None;self.started=time.monotonic()
    async def checkpoint(self,phase):
        state=(await self.ipc.call('state'))['state']
        require(state['quarantined'] is False and state['active'] is False and state['pending']==0 and state['retired']==0 and state['errors']==0)
        self.checkpoints.append(dict(phase=phase,service=state,client=scalar_resources(),elapsed=round(time.monotonic()-self.started,6)))
    async def attempt(self,index,fault):
        # Attempt ledger is appended before any resource acquisition; failures remain.
        row=dict(index=index,fault=fault,status='failed',cleanup_confirmed=False,client_cleanup=False,stage='configure')
        self.rows.append(row);relay=TcpRelay(self.port);ws=None;wire=None;tasks=set();self.current=(relay,tasks)
        try:
            async with asyncio.timeout(6):
                await self.ipc.call('configure',text_index=index%4,fault=fault)
                row['stage']='connect';port=await relay.start()
                from websockets.asyncio.client import connect
                ws=await connect(f'wss://127.0.0.1:{port}/v2/voice',ssl=self.tls,server_hostname='localhost',additional_headers={'Authorization':'Bearer '+TOKEN},max_size=16000,max_queue=4,write_limit=16000,close_timeout=.2,open_timeout=2)
                wire=Wire(ws,self.ipc,fault,self.old_ack);tasks={asyncio.create_task(wire.receive()),asyncio.create_task(wire.heartbeat())};self.current=(relay,tasks)
                row['stage']='wire';await wire.command('scope');await wire.scope.wait();await wire.command('wake');await wire.input()
                if fault=='asr_rst':await self.ipc.call('entered',stage='asr')
                else:
                    await wire.seal()
                    if fault in {'plan_rst','pause_resume'}:await self.ipc.call('entered',stage='plan')
                    elif fault in {'partial_rst','half_open','playback_stop'}:await wire.acked.wait()
                row['stage']='fault';row['rst_applied']=None;row['pause_observed']=None
                if fault in {'asr_rst','plan_rst','partial_rst'}:row['rst_applied']=relay.reset();require(row['rst_applied'])
                elif fault=='half_open':
                    relay.pause('up');relay.pause('down');await asyncio.sleep(.05)
                    row['pause_observed']=relay.blocked['down'].is_set();row['rst_applied']=relay.reset();require(row['pause_observed'] and row['rst_applied'])
                elif fault=='pause_resume':
                    relay.pause('down');await self.ipc.call('unblock');await relay.blocked['down'].wait()
                    row['pause_observed']=True;await asyncio.sleep(.05);relay.resume('down');await wire.done.wait();require(wire.delivered)
                elif fault=='playback_stop':
                    await wire.command('stop',intent='persistent-interrupt')
                    await self.ipc.call('barrier',seq=wire.seq-1)
                else:await wire.done.wait();require(wire.delivered)
                row['status']='interrupted' if fault=='playback_stop' else 'fault_injected' if fault in {'asr_rst','plan_rst','partial_rst','half_open'} else 'delivered'
                if index==0:
                    row['continuous']=dict(turns=[],stop=dict(status='not_started'),recovery=dict(status='not_started'),same_connection=True,stop_recovered=False,old_ack_rejected=False,stop_pending=None)
                    await self.continuous(wire,row['continuous'])
                state=(await self.ipc.call('state'))['state']
                row.update(frames=wire.frames,acks=wire.acks,control=wire.control,new_session=state['new_session'],heard_before_close=state['heard'],game_mode=state['game'],old_ack_checked=wire.old_checked,binding=state['binding'],same_session=state['same_session'])
                self.old_ack=wire.last_ack or self.old_ack
                row['stage']='cleanup'
        except BaseException as error:
            row['status']='failed'
            row['failure_kind']='cancelled' if isinstance(error,asyncio.CancelledError) else 'timeout' if isinstance(error,TimeoutError) else 'wire_or_provider'
            raise
        finally:
            if wire:row.update(frames=wire.frames,acks=wire.acks,control=wire.control,old_ack_checked=wire.old_checked)

            if ws:
                close=asyncio.create_task(ws.close());tasks.add(close);await asyncio.wait({close},timeout=.3)
                if not close.done():ws.transport.abort()
                row['close_handshake_confirmed']=close.done() and not close.cancelled() and close.exception() is None and ws.close_code==1000
            for task in tasks:
                if not task.done():task.cancel()
            confirmed,pending,errors=await relay.close(time.monotonic()+.6)
            client_ok,client_pending,client_errors=await drain(lambda:tasks|relay.tasks,time.monotonic()+.6)
            # ConnectionClosed is expected for injected RST only; receive result is still observed.
            if client_errors and fault in {'asr_rst','plan_rst','partial_rst','half_open'}:
                unexpected=[t.exception() for t in tasks if t.done() and not t.cancelled() and t.exception() is not None and not isinstance(t.exception(),ConnectionClosed)]
                client_errors=len(unexpected)
            row['client_cleanup']=confirmed and client_ok and not pending and not errors and not client_errors
            # drain's boolean includes expected connection resets; handle explicitly above.
            if not pending and not client_pending and not errors and not client_errors:row['client_cleanup']=True
            try:
                released=(await self.ipc.call('release',allow_failure=True))['state'];row['service_cleanup']=released
                row['cleanup_confirmed']=released['cleanup_confirmed'] and row['client_cleanup']
            except Exception:row['cleanup_confirmed']=False
            row.update(relay_bytes=dict(relay.bytes),relay_buffer_observed_max=relay.buffer_peak,relay_network_errors=relay.network_errors)
            if row['cleanup_confirmed']:self.current=None
            else:
                row['status']='failed';row['failure_kind']='cleanup_unconfirmed'
                raise Rejected('cleanup_unconfirmed')
        try:validate_attempt(row)
        except Exception:
            row['status']='failed';row['stage']='validation';row['failure_kind']='evidence_invalid'
            raise Rejected('evidence_invalid') from None
    async def continuous(self,wire,record):
        """Same real socket/session: story->adventure->stop->association."""
        start=(await self.ipc.call('state'))['state'];out=record['turns']
        require(start['same_session'] is True and hex_string(start['binding'],64) and hex_string(start['played_anchor'],64))
        record['initial_binding']=start['binding'];record['initial_anchor']=start['played_anchor'];record['initial_played_count']=start['played_count'];previous_count=start['played_count']
        for text_index,mode in ((1,'story'),(2,'adventure')):
            step=dict(mode=mode,status='attempted',delivered=False);out.append(step)
            await self.ipc.call('configure',text_index=text_index,fault='normal_close');await wire.input();await wire.seal();await wire.done.wait();require(wire.delivered)
            state=(await self.ipc.call('state'))['state'];require(state['constructed']==start['constructed'] and state['game']==mode and state['heard']>0 and state['same_session'] is True and state['binding']==start['binding'] and state['played_anchor']==start['played_anchor'] and state['played_count']>previous_count)
            step.update(status='delivered',delivered=True,constructed=state['constructed'],state_hash=state['state_hash'],binding=state['binding'],same_session=state['same_session'],played_anchor=state['played_anchor'],played_count=state['played_count']);previous_count=state['played_count']
        # Partially ACK a new output and stop it, then a genuine same-session recovery.
        record['stop']['status']='attempted';before_stop=(await self.ipc.call('state'))['state']
        wire.fault='playback_stop';await self.ipc.call('configure',text_index=2,fault='normal_close')
        await wire.input();await wire.seal();await wire.acked.wait();await wire.command('stop',intent='continuous-stop')
        await self.ipc.call('barrier',seq=wire.seq-1)
        await self.ipc.call('configure',text_index=3,fault='normal_close')
        wire.old_ack=wire.last_ack;wire.old_checked=None
        stopped=(await self.ipc.call('state'))['state'];require(not stopped['generation'] and stopped['pending_audio']==0 and stopped['heard']==before_stop['heard'])
        require(stopped['same_session'] is True and stopped['binding']==start['binding'] and stopped['played_anchor']==start['played_anchor'])
        record['stop'].update(binding=stopped['binding'],same_session=stopped['same_session'],played_anchor=stopped['played_anchor'],status='interrupted',heard_before=before_stop['heard'],heard_after=stopped['heard'],pending=stopped['pending_audio'],played_count=stopped['played_count'])
        record['recovery']['status']='attempted'
        wire.fault='normal_close';await wire.input();await wire.seal();await wire.done.wait();require(wire.delivered and wire.old_checked is True)
        await self.ipc.call('configure',text_index=3,fault='normal_close')
        state=(await self.ipc.call('state'))['state'];require(state['constructed']==start['constructed'] and state['game']=='association' and not state['pending_audio'] and not state['generation'])
        require(state['same_session'] is True and state['binding']==start['binding'] and state['played_anchor']==start['played_anchor'] and state['played_count']>previous_count)
        record['recovery'].update(binding=state['binding'],same_session=state['same_session'],played_anchor=state['played_anchor'],status='delivered',mode=state['game'],constructed=state['constructed'],played_count=state['played_count'])
        record.update(stop_recovered=True,old_ack_rejected=wire.old_checked,stop_pending=stopped['pending_audio'],final=state)

def validate_attempt(row):
    """Factual fault/ACK/cleanup evidence, never labels alone."""
    require(type(row) is dict and type(row.get('index')) is int and 0<=row['index']<42)
    fault=MATRIX[(row['index']//2)%7] if row['index']%2==0 else 'normal_close'
    require(row.get('fault')==fault and row.get('cleanup_confirmed') is True and row.get('client_cleanup') is True)
    state=row['service_cleanup']
    require(state.get('transport_closed') is True and row.get('same_session') is True and state.get('same_session') is True and hex_string(row.get('binding'),64) and row['binding']==state.get('binding'))
    require(state['cleanup_confirmed'] is True and state['finished'] is True and state['active'] is False and state['quarantined'] is False)
    require(all(type(state[k]) is int and state[k]==0 for k in ('pending','retired','errors','heard','pending_audio')))
    require(row.get('new_session') is True and row.get('control') is None)
    for key in ('frames','acks'):require(type(row.get(key)) is int and 0<=row[key]<=2048)
    require(0<=row['acks']<=row['frames'])
    expected='interrupted' if fault=='playback_stop' else 'fault_injected' if fault in {'asr_rst','plan_rst','partial_rst','half_open'} else 'delivered'
    require(row.get('status')==expected)
    require(row.get('rst_applied') is True if expected=='fault_injected' else row.get('rst_applied') is None)
    require(row.get('pause_observed') is True if fault in {'pause_resume','half_open'} else row.get('pause_observed') is None)
    require(type(row.get('relay_bytes')) is dict and row['relay_bytes'].keys()=={'up','down'} and all(type(v) is int and v>0 for v in row['relay_bytes'].values()))
    require(type(row.get('relay_buffer_observed_max')) is int and 0<row['relay_buffer_observed_max']<=16384)
    if expected=='delivered':
        # First connection includes a deliberately partial output before stop.
        require(row['frames']>=row['acks']>0 and (row['index']==0 or row['frames']==row['acks']))
        require(type(row.get('heard_before_close')) is int and row['heard_before_close']>0 and row.get('close_handshake_confirmed') is True)
    elif fault in {'asr_rst','plan_rst'}:require(row['frames']==row['acks']==0 and row.get('heard_before_close')==0)
    else:require(row['frames']>=row['acks']==1 and row.get('heard_before_close')==0)
    if row['index']>0 and row['frames']:require(row.get('old_ack_checked') is True)
    if row['index']==0:
        continuous=row['continuous'];require(continuous['same_connection'] is True and continuous['stop_recovered'] is True and continuous['old_ack_rejected'] is True and continuous['stop_pending']==0)
        require(hex_string(continuous.get('initial_binding'),64) and continuous['initial_binding']==row['binding'] and hex_string(continuous.get('initial_anchor'),64))
        for step in continuous['turns']+[continuous['stop'],continuous['recovery'],continuous['final']]:
            require(step.get('binding')==continuous['initial_binding'] and step.get('same_session') is True and step.get('played_anchor')==continuous['initial_anchor'])
        turns=continuous['turns'];require(len(turns)==2 and [r['mode'] for r in turns]==['story','adventure'])
        require(all(r['delivered'] is True and r['constructed']==1 for r in turns))
        counts=[continuous['initial_played_count']]+[r['played_count'] for r in turns]
        require(all(type(n) is int and n>0 for n in counts) and all(b>a for a,b in zip(counts,counts[1:])))
        require(continuous['stop']['played_count']==counts[-1] and continuous['recovery']['played_count']>counts[-1] and continuous['final']['played_count']==continuous['recovery']['played_count'])
        require(continuous['stop']['status']=='interrupted' and continuous['stop']['heard_before']==continuous['stop']['heard_after'] and continuous['stop']['pending']==0)
        require(continuous['recovery']['status']=='delivered' and continuous['recovery']['mode']=='association' and continuous['recovery']['constructed']==1)
        require(continuous['final']['constructed']==1 and continuous['final']['game']=='association' and continuous['final']['pending_audio']==0)

async def run_driver(output,rounds,source,lock_fd,supervisor_pid,run_id,authority):
    output=Path(output);rows=[];checkpoints=[];driver=None;process=None;ipc=None
    report=dict(format=1,source_sha=source,status='failed_or_unknown_stopped',layer='persistent_service_separate_driver_loopback_tls',
        cloud_enabled=False,device_executed=False,seed=17,protocol_contract=CONTRACT,rounds_requested=rounds,attempts=rows,checkpoints=checkpoints,
        full_acceptance=False,p14_verified=False,continuous_peaks_known=False,gc_forced=False,cleanup_confirmed=False,service_forced_exit=False,authority=authority,shutdown=None)
    def save():
        # Only bounded scalars/hash/enums, never identities, raw messages or packets.
        report['connection_count']=len(rows)
        (output/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    save()
    try:
        with tempfile.TemporaryDirectory(prefix='persistent-tls-') as folder:
            root=Path(folder)
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost',
                '-keyout',str(root/'key'),'-out',str(root/'cert')],check=True,timeout=5,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            a,b=socket.socketpair();a.setblocking(False)
            try:
                process=subprocess.Popen([sys.executable,'-I','-B',str(Path(__file__).resolve()),'_service','--enable','--fd',str(b.fileno()),'--cert',str(root/'cert'),'--key',str(root/'key'),'--lock-fd',str(lock_fd),'--supervisor-pid',str(supervisor_pid),'--parent-pid',str(os.getpid()),'--driver-pid',str(os.getpid()),'--source',source,'--run-id',run_id],
                    pass_fds=(b.fileno(),lock_fd),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            finally:b.close()
            ipc=await channel(a.detach());hello=await ipc.receive()
            require(hello.get('ok') is True and hello.get('pid')==process.pid and hello.get('protocol')==CONTRACT and hello.get('authority')==authority)
            report['service_pid']=process.pid;report['driver_pid']=os.getpid()
            tls=ssl.create_default_context(cafile=root/'cert')
            driver=Driver(ipc,tls,hello['port'],rounds);rows=driver.rows;checkpoints=driver.checkpoints;report.update(attempts=rows,checkpoints=checkpoints)
            async with asyncio.timeout(SECONDS-10):
                await driver.checkpoint('before_warmup')
                for index in range(rounds*14):
                    fault=MATRIX[(index//2)%7] if index%2==0 else 'normal_close'
                    await driver.attempt(index,fault);save()
                    if index==1:await driver.checkpoint('after_warmup')
                    if index%14==13:await driver.checkpoint('after_round_'+str(index//14+1));save()
                report['shutdown']=(await ipc.call('shutdown'))['state']
            # Never a replacement service, even after unconfirmed cleanup.
            async with asyncio.timeout(2):
                while process.poll() is None:await asyncio.sleep(.01)
            require(process.returncode==0)
            report.update(status='collected_not_stability_verdict',cleanup_confirmed=True,service_exit=0,
                connection_count=len(rows),allowance=report['shutdown']['allowance'])
    except BaseException as error:
        report['failure_kind']='cancelled' if isinstance(error,asyncio.CancelledError) else 'timeout' if isinstance(error,TimeoutError) else 'unconfirmed'
    finally:
        if ipc:ipc.writer.close()
        if process and process.poll() is None:
            # Process containment is recorded, never mislabelled provider cleanup.
            process.kill();process.wait(timeout=2);report['service_forced_exit']=True;report['cleanup_confirmed']=False;report['status']='failed_or_unknown_stopped'
        save()
    return report

def supervise(output,rounds):
    require(type(rounds) is int and 1<=rounds<=3)
    output=Path(output).resolve()
    with heavy_lock() as fd:
        info=os.fstat(fd);expected_lock=digest([info.st_dev,info.st_ino])
        output.mkdir(exist_ok=False)
        source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).resolve().parents[1],timeout=2,text=True).strip();run_id=secrets.token_hex(16)
        args=[sys.executable,'-I','-B',str(Path(__file__).resolve()),'_driver','--enable','--output',str(output),'--rounds',str(rounds),'--source',source,'--lock-fd',str(fd),'--supervisor-pid',str(os.getpid()),'--parent-pid',str(os.getpid()),'--run-id',run_id]
        process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,pass_fds=(fd,),start_new_session=True)
        try:code=process.wait(timeout=SECONDS+5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=2)
            (output/'supervisor.json').write_text(json.dumps(dict(status='timeout_killed_group',cleanup_confirmed=False,no_retry=True))+'\n')
            raise Rejected('supervisor_timeout') from None
        except BaseException:
            os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=2)
            (output/'supervisor.json').write_text(json.dumps(dict(status='cancelled_killed_group',cleanup_confirmed=False,no_retry=True))+'\n')
            raise Rejected('supervisor_cancelled') from None
        (output/'supervisor.json').write_text(json.dumps(dict(status='child_returned',exit_code=code,no_retry=True))+'\n')
        path=output/'result.json'
        try:
            require(path.is_file() and not path.is_symlink() and path.stat().st_size<512000)
            result=json.loads(path.read_text());validate_report(result,rounds,source);require(code==0 and result['authority']['run_digest']==digest(run_id) and result['authority']['lock_identity']==expected_lock)
        except Exception:
            (output/'supervisor.json').write_text(json.dumps(dict(status='validation_failed',exit_code=code,cleanup_confirmed=False,no_retry=True))+'\n')
            raise Rejected('supervisor_validation_failed') from None
        return result

SUCCESS_FIELDS={'format','source_sha','status','layer','cloud_enabled','device_executed','seed','protocol_contract','rounds_requested',
    'attempts','checkpoints','full_acceptance','p14_verified','continuous_peaks_known','gc_forced','cleanup_confirmed',
    'service_forced_exit','authority','shutdown','connection_count','service_pid','driver_pid','service_exit','allowance'}

def validate_report(result,rounds,source):
    try:return _validate_report(result,rounds,source)
    except (KeyError,TypeError,ValueError,IndexError,AttributeError):raise Rejected('report_incomplete') from None

def _validate_report(result,rounds,source):
    require(type(result) is dict and result.keys()==SUCCESS_FIELDS and result['layer']=='persistent_service_separate_driver_loopback_tls')
    require(result['service_forced_exit'] is False and type(result['service_exit']) is int and result['service_exit']==0)
    require(all(result[k] is False for k in ('full_acceptance','p14_verified','continuous_peaks_known')))
    authority=result['authority'];require(type(authority) is dict and authority.keys()=={'source_sha','lock_identity','run_digest'} and authority['source_sha']==source and all(hex_string(authority[k],64) for k in ('lock_identity','run_digest')))
    require(result.get('source_sha')==source and result.get('format')==1 and result.get('rounds_requested')==rounds and result.get('seed')==17 and result.get('protocol_contract')==CONTRACT)
    require(result.get('status')=='collected_not_stability_verdict' and result.get('cleanup_confirmed') is True and result.get('service_exit')==0)
    require(result.get('cloud_enabled') is False and result.get('device_executed') is False and result.get('gc_forced') is False)
    require(type(result.get('service_pid')) is int and type(result.get('driver_pid')) is int and result['service_pid']!=result['driver_pid'])
    rows=result['attempts'];require(type(rows) is list and len(rows)==rounds*14==result['connection_count'])
    bindings=set()
    for index,row in enumerate(rows):
        require(row.get('index')==index);validate_attempt(row);require(row['binding'] not in bindings);bindings.add(row['binding'])
    shutdown=result['shutdown'];require(type(shutdown) is dict and shutdown['constructed']==rounds*14 and shutdown['finished'] is True and shutdown['active'] is False and shutdown['quarantined'] is False and shutdown['binding'] is None)
    require(all(type(shutdown[k]) is int and shutdown[k]==0 for k in ('pending','retired','errors','heard','pending_audio')))
    require(type(result['allowance']) is dict and result['allowance']==shutdown['allowance'])
    allowance=result['allowance'];require(allowance.keys()=={'model_calls','tts_calls','tts_unicode_characters','reserved_units','account_quota_known','bill_cny'})
    require(allowance['account_quota_known'] is False and allowance['bill_cny'] is None)
    for key,cap in (('model_calls',360),('tts_calls',64),('tts_unicode_characters',8192),('reserved_units',424)):
        require(type(allowance[key]) is int and 0<=allowance[key]<=cap)
    points=result['checkpoints'];require([p['phase'] for p in points]==['before_warmup','after_warmup']+['after_round_'+str(i+1) for i in range(rounds)])
    previous=-1
    for i,point in enumerate(points):
        require(type(point['elapsed']) in (int,float) and previous<=point['elapsed']<=SECONDS);previous=point['elapsed']
        state=point['service'];require(state['quarantined'] is False and state['active'] is False and all(type(state[k]) is int and state[k]==0 for k in ('pending','retired','errors')))
        require(state['constructed']==(0 if i==0 else 2 if i==1 else (i-1)*14))
        for sample in (point['client'],state['resources']):
            require(sample.keys()=={'backend_rss_bytes','backend_fds','backend_threads','asyncio_tasks'})
            require(all(type(v) is int and v>0 for v in sample.values()))


def cli(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=('prepare','_driver','_service'))
    parser.add_argument('--enable',action='store_true');parser.add_argument('--output',type=Path);parser.add_argument('--rounds',type=int,default=3)
    parser.add_argument('--lock-fd',type=int);parser.add_argument('--supervisor-pid',type=int);parser.add_argument('--parent-pid',type=int);parser.add_argument('--driver-pid',type=int);parser.add_argument('--run-id')
    parser.add_argument('--fd',type=int);parser.add_argument('--cert');parser.add_argument('--key');parser.add_argument('--source')
    args=parser.parse_args(argv)
    if not args.enable:return 2
    try:
        require(1<=args.rounds<=3)
        if args.mode=='prepare':supervise(args.output,args.rounds)
        else:
            with internal_authority(args) as authority:
                if args.mode=='_driver':
                    result=asyncio.run(run_driver(args.output,args.rounds,args.source,args.lock_fd,args.supervisor_pid,args.run_id,authority));return 0 if result['cleanup_confirmed'] else 2
                else:asyncio.run(serve_child(args.fd,args.cert,args.key,authority))
        return 0
    except BaseException:return 2 # no arbitrary exception body/child stderr

if __name__=='__main__':raise SystemExit(cli())
