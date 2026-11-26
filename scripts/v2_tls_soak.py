"""Optional synthetic-only loopback TLS soak; no public listener or cloud factory.

The TCP relay handles ciphertext only. Local faults aren't phone/supplier weak-net
or acoustic evidence. Neither a short run nor 3600 seconds implies A36/P14 PASS.
"""
import asyncio
import base64
from contextlib import asynccontextmanager
import json
from pathlib import Path
import random
import socket
import ssl
import struct
import subprocess
import tempfile
import time
from unittest.mock import patch

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from backend.v2.server import voice_server
from backend.v2.protocol import CONTRACT
from backend.v2.voice import VoicePeer
from backend.v2.companion import UnifiedProviders, CompanionPolicy
from scripts.v2_soak import (Limits, Allowance, MeterModel, OfflineModel, ResourceCollector,
                             ObservedScopes, ObservedRetired)

TOKEN='SyntheticOnly'*4
# All triggers use actual wire entry points. A recovery is a separate ledger row.
MATRIX=('normal_close','asr_rst','plan_rst','partial_rst','pause_resume','half_open','playback_stop')
TEXTS=('你出动物谜语我猜，每次一条线索。','我们轮流编小猫飞船的故事。',
       '改成太空探险，我当船长。','轮流说红色水果，不重复。')

async def wait_pred(predicate,seconds=2):
    async with asyncio.timeout(seconds):
        while not predicate():await asyncio.sleep(.002)

async def drain(handles,deadline):
    """Dynamic registry, including done tasks registered by done callbacks.

    Never wait_for a cancellation-swallowing coroutine. Unconfirmed handles stay
    owned by the caller; restoring a provider or restarting is forbidden.
    """
    observed=set();errors=0
    while True:
        tasks=set(handles())-{asyncio.current_task()};fresh=tasks-observed
        for task in fresh:
            if task.done():
                observed.add(task)
                if not task.cancelled() and task.exception() is not None:errors+=1
        pending={t for t in tasks if not t.done()}
        if not pending:
            await asyncio.sleep(0)
            if set(handles())-{asyncio.current_task()}<=observed:return not errors,set(),errors
        remaining=deadline-time.monotonic()
        if remaining<=0:return False,{t for t in handles() if t is not asyncio.current_task() and not t.done()},errors
        if pending:await asyncio.wait(pending,timeout=min(.02,remaining))

class TcpRelay:
    """One 4096-byte slot per direction/connection, finite writer buffers.

    No application decryption, body logs, packet storage, DNS, or outside target.
    pause gates the next read; at most one already-read chunk can be in flight.
    """
    def __init__(self,target_port):
        self.target_port=target_port;self.tasks=set();self.links=[];self.server=None
        self.bytes={'up':0,'down':0};self.buffer_peak=0;self.open=True;self.network_errors=0
        self.accepted=asyncio.Event()
        self.gates={k:asyncio.Event() for k in ('up','down')}
        for event in self.gates.values():event.set()
        self.blocked={k:asyncio.Event() for k in ('up','down')}
    async def start(self):
        self.server=await asyncio.start_server(self.accept,'127.0.0.1',0,limit=8192)
        return self.server.sockets[0].getsockname()[1]
    def track(self,task):self.tasks.add(task);return task
    def accept(self,reader,writer):
        if self.accepted.is_set() or not self.open:writer.transport.abort();return
        self.accepted.set();self.track(asyncio.create_task(self.forward(reader,writer)))
    async def forward(self,reader,writer):
        remote=None
        try:
            async with asyncio.timeout(2):remote_reader,remote=await asyncio.open_connection('127.0.0.1',self.target_port,limit=8192)
            self.links.append((writer,remote))
            for w in (writer,remote):w.transport.set_write_buffer_limits(high=8192,low=4096)
            async def pipe(source,dest,direction):
                try:
                    await self.pipe_bytes(source,dest,direction)
                except (OSError,ConnectionError):self.network_errors+=1
            pumps={self.track(asyncio.create_task(pipe(reader,remote,'up'))),self.track(asyncio.create_task(pipe(remote_reader,writer,'down')))}
            await asyncio.wait(pumps,return_when=asyncio.FIRST_COMPLETED)
            for task in pumps:
                if not task.done():task.cancel()
        except (OSError,ConnectionError,TimeoutError):self.network_errors+=1
        finally:
            writer.close()
            if remote:remote.close()
    async def pipe_bytes(self,source,dest,direction):
        while self.open:
            if not self.gates[direction].is_set():self.blocked[direction].set()
            await self.gates[direction].wait()
            chunk=await source.read(4096)
            if not chunk:return
            if not self.gates[direction].is_set():self.blocked[direction].set()
            await self.gates[direction].wait()
            self.bytes[direction]+=len(chunk)
            self.buffer_peak=max(self.buffer_peak,len(chunk)+dest.transport.get_write_buffer_size())
            dest.write(chunk);await dest.drain()
    def pause(self,direction):self.blocked[direction].clear();self.gates[direction].clear()
    def resume(self,direction):self.gates[direction].set()
    def reset(self):
        applied=0
        for pair in self.links:
            for writer in pair:
                raw=writer.get_extra_info('socket')
                if raw:
                    try:raw.setsockopt(socket.SOL_SOCKET,socket.SO_LINGER,struct.pack('ii',1,0));applied+=1
                    except OSError:self.network_errors+=1
                writer.transport.abort()
        return applied>0
    async def close(self,deadline=None):
        deadline=deadline if deadline is not None else time.monotonic()+.6
        self.open=False
        # A connect cancelled during handshake may already have queued one accept.
        # Wait for that actual callback before closing its listening server.
        if not self.accepted.is_set():
            waiter=asyncio.create_task(self.accepted.wait())
            await asyncio.wait({waiter},timeout=min(.1,max(0,deadline-time.monotonic())))
            waiter.cancel();await asyncio.gather(waiter,return_exceptions=True)
        for event in self.gates.values():event.set()
        self.reset()
        if self.server:self.server.close();await self.server.wait_closed()
        for task in self.tasks:
            if not task.done():task.cancel()
        return await drain(lambda:self.tasks,deadline)

class SyntheticSpeech:
    def __init__(self,allowance):
        self.allowance=allowance;self.text='';self.asr_entered=asyncio.Event();self.asr_gate=asyncio.Event();self.asr_gate.set()
        self.asr_calls=0;self.asr_active=0;self.tts_active=0;self.tts_entered=0;self.tts_exited=0;self.release=asyncio.Event();self.release.set();self.stubborn=False
    @asynccontextmanager
    async def recognize(self,rate):
        self.asr_calls+=1;self.asr_active+=1;self.asr_entered.set();owner=self
        class Recognition:
            async def write(self,pcm):pass
            async def finish(self):await owner.asr_gate.wait();return owner.text
        try:yield Recognition()
        finally:self.asr_active-=1
    @asynccontextmanager
    async def synthesize(self,text,rate):
        self.allowance.take('tts',len(text));self.tts_active+=1;self.tts_entered+=1
        async def frames():
            for _ in range(4):yield b'\x01\x00'*2400;await asyncio.sleep(.01)
        try:yield frames()
        finally:
            if self.stubborn:
                while not self.release.is_set():
                    try:await self.release.wait()
                    except asyncio.CancelledError:continue
            self.tts_active-=1;self.tts_exited+=1

class NetworkMeter(MeterModel):
    async def complete(self,instruction,data,*,schema=None):
        if 'completion' not in (schema or {}).get('properties',{}):
            return await super().complete(instruction,data,schema=schema)
        self.allowance.take('model');self.stages['endpoint']=self.stages.get('endpoint',0)+1
        if len(instruction.encode())>32768 or len(json.dumps(data,ensure_ascii=False).encode())>32768:raise RuntimeError('request_size')
        try:return await self.inner.complete(instruction,data,schema=schema)
        except BaseException:self.failures+=1;raise

class SyntheticModel(OfflineModel):
    def __init__(self):self.plan_entered=asyncio.Event();self.plan_gate=asyncio.Event();self.plan_gate.set()
    async def complete(self,instruction,data,*,schema=None):
        props=(schema or {}).get('properties',{})
        if 'completion' in props:return '{"completion":"complete","meaning":"new_turn"}'
        if 'mode' in props:self.plan_entered.set();await self.plan_gate.wait()
        return await super().complete(instruction,data,schema=schema)

class LoopbackTlsTransport:
    def __init__(self,limits,seed=17):
        limits.validate()
        if type(seed) is not int or not 0<=seed<=2**32-1:raise ValueError('seed')
        self.limits=limits;self.seed=seed;self.allowance=Allowance(limits);self.started=time.monotonic()
        self.speech=SyntheticSpeech(self.allowance);self.model=SyntheticModel();self.meter=NetworkMeter(self.model,self.allowance)
        self.providers=UnifiedProviders(self.speech,self.meter)
        self.peers=[];self.tasks=set();self.connections=[];self.relays=[];self.closed=False;self.quarantined=False
        self.collector=ResourceCollector(self,self.allowance,self.started)
        extra=('active_sessions','visual_pending','capture_bytes','asr_active','tts_active','recognition_operations','server_handlers_pending','relay_buffer_observed_max')
        self.collector.trends.update({k:dict(first=None,last=None,maximum=None) for k in extra})
        self.collector.PHASES=self.collector.PHASES|{'before_network_fault','after_network_fault'}
        self.server=None;self.patcher=None;self.temp=None;self.ws=None;self.current=None;self.send_lock=asyncio.Lock()
        self.history=set();self.error_count=0;self.loop_events=[];self.loop=None;self.old_exception_handler=None;self.previous_ack=None;self.previous_session=None
    async def start(self):
        self.temp=tempfile.TemporaryDirectory(prefix='v2-loopback-');root=Path(self.temp.name)
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost',
                        '-addext','subjectAltName=DNS:localhost','-keyout',str(root/'key'),'-out',str(root/'cert')],
                       check=True,timeout=5,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(root/'cert',root/'key')
        self.client_tls=ssl.create_default_context(cafile=str(root/'cert'));owner=self
        class ObservedPeer(VoicePeer):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs);self.retained=set();self.run_finished=False;owner.peers.append(self)
                self.generation_scopes=ObservedScopes(self.generation_scopes,owner.collector.record)
                self.retired_tasks=ObservedRetired(self.retired_tasks,owner.collector.record)
                owner.collector.record('initial')
            def track_retired(self,task):self.retained.add(task);return super().track_retired(task)
            async def run(self):
                owner.tasks.add(asyncio.current_task())
                try:return await super().run()
                finally:self.run_finished=True;owner.collector.record('after_transport_cleanup')
        # Scoped instrumentation only; production run/handle/cleanup are delegated.
        # Single loopback instance per process, never patch a concurrently served endpoint.
        self.patcher=patch('backend.v2.server.VoicePeer',ObservedPeer);self.patcher.start()
        self.loop=asyncio.get_running_loop();self.old_exception_handler=self.loop.get_exception_handler()
        def safe_loop_event(loop,context):
            error=context.get('exception')
            code='connection_reset' if isinstance(error,(ConnectionResetError,ConnectionAbortedError,BrokenPipeError)) else 'unexpected_loop_failure'
            self.loop_events.append(code)
            if code=='unexpected_loop_failure':self.quarantined=True;self.allowance.open=False
        self.loop.set_exception_handler(safe_loop_event)
        self.server=await voice_server('127.0.0.1',0,tls,TOKEN,self.providers,CompanionPolicy())
        self.port=self.server.sockets[0].getsockname()[1]
    def sample(self):
        peers=self.peers
        return dict(active_sessions=sum(not p.closed and p.session.active for p in peers),
                    active_operations=sum(len(p.generation_scopes) for p in peers),
                    retired_pending=sum(not t.done() for p in peers for t in p.retained|set(p.retired_tasks)),
                    generation_pending=sum(p.generation is not None and not p.generation.done() for p in peers),
                    visual_pending=sum(p.visual_task is not None and not p.visual_task.done() for p in peers),
                    capture_bytes=sum(len(p.capture) for p in peers),recognition_operations=sum(len(p.recognition_scopes) for p in peers),
                    server_handlers_pending=sum(not t.done() for t in self.server.handler_tasks) if self.server else 0,asr_active=self.speech.asr_active,tts_active=self.speech.tts_active,
                    transport_tasks_pending=sum(not t.done() for t in self.tasks)+sum(not t.done() for r in self.relays for t in r.tasks),
                    relay_buffer_observed_max=max((r.buffer_peak for r in self.relays),default=0))
    def handles(self):
        tasks=set(self.tasks)
        for relay in self.relays:tasks|=relay.tasks
        for p in self.peers:
            tasks|=p.retained|set(p.retired_tasks)
            tasks|={t for t in (p.generation,p.recognition,p.visual_task) if t is not None}
        return tasks
    async def command(self,kind,**fields):
        async with self.send_lock:
            row=self.current
            if kind=='stop':row['epoch']+=1;row['seq']=0
            await self.ws.send(json.dumps(dict(v=2,type=kind,epoch=row['epoch'],seq=row['seq'],**fields)))
            row['seq']+=1
    async def receive(self):
        row=self.current
        try:
            async for raw in self.ws:
                event=json.loads(raw);kind=event['type']
                if event.get('epoch')!=row['epoch']:continue
                if kind=='scope':
                    if event.get('protocol_contract')!=CONTRACT or event.get('management_v')!=1:raise RuntimeError('contract')
                    row['scope'].set()
                elif kind=='endpoint':row['endpoint'].set()
                elif kind=='decision':await self.command('stop',intent=event['intent'])
                elif kind=='open':await self.command('bind',player='synthetic-network-player')
                elif kind=='bound':row['identity']=event['identity'];row['bound'].set()
                elif kind=='audio':
                    row['frames']+=1;row['first_at']=row['first_at'] or time.monotonic();row['first'].set()
                    if row['fault'] in {'partial_rst','half_open','playback_stop'} and row['frames']>1:continue
                    identity=dict(row['identity'],sequence=row['ack_seq']);row['ack_seq']+=1
                    ack=dict(identity=identity,player=event['player'],stream=event['stream'],segment=event['segment'],head=event['end'])
                    if self.previous_ack is not None and not row.get('old_ack_checked'):
                        peer=row['peer'];before=(peer.session.head,len(peer.session.context().get('heard',())),dict(peer.session.game))
                        await self.command('ack',**self.previous_ack);sent=row['seq']-1
                        await wait_pred(lambda:peer.sequence>=sent)
                        after=(peer.session.head,len(peer.session.context().get('heard',())),dict(peer.session.game))
                        row['old_ack_checked']=before==after
                        if before!=after:raise RuntimeError('old_ack_changed_state')
                    row['last_ack']=ack;await self.command('ack',**ack)
                    row['acked'].set()
                elif kind=='reply_end':row['delivered']=True;row['done'].set()
                elif kind=='failure':
                    row['control']=event.get('code') if event.get('code') in {'voice','timeout','network','quota','safety'} else 'unknown';row['done'].set()
        except ConnectionClosed:row['wire_closed']=True
        finally:row['done'].set()
    async def heartbeat(self):
        try:
            while True:await self.command('heartbeat');await asyncio.sleep(5)
        except ConnectionClosed:return
    async def attempt(self,text,fault):
        if self.quarantined or self.closed:raise RuntimeError('isolated')
        if len(self.connections)>=self.limits.max_attempts:raise RuntimeError('attempt_cap')
        if fault not in MATRIX:raise ValueError('fault')
        row=dict(index=len(self.connections),fault=fault,epoch=0,seq=0,ack_seq=0,identity=None,frames=0,first_at=None,
                 last_ack=None,delivered=False,wire_closed=False,control=None,status='failed',cleanup_confirmed=False)
        for name in ('first','endpoint','bound','done','acked','scope'):row[name]=asyncio.Event()
        row['started']=time.monotonic()
        self.connections.append(row);self.current=row;self.speech.text=text
        self.speech.asr_entered.clear();self.speech.asr_gate.set();self.model.plan_entered.clear();self.model.plan_gate.set()
        if fault=='asr_rst':self.speech.asr_gate.clear()
        if fault in {'plan_rst','pause_resume'}:self.model.plan_gate.clear()
        relay=TcpRelay(self.port);self.relays.append(relay);port=await relay.start();row['relay']=relay
        previous=self.peers[-1] if self.peers else None;self.collector.record('attempt_started')
        try:
            self.ws=await connect(f'wss://127.0.0.1:{port}/v2/voice',ssl=self.client_tls,server_hostname='localhost',
                                  additional_headers={'Authorization':'Bearer '+TOKEN},max_size=16000,max_queue=4,write_limit=16000,close_timeout=.2,open_timeout=2)
            # Busy/quarantined servers must never be represented as successful reconnects.
            await wait_pred(lambda:bool(self.peers) and self.peers[-1] is not previous)
            peer=self.peers[-1];row['peer']=peer
            row['new_session']=self.previous_session is None or self.previous_session!=peer.session.session
            self.previous_session=peer.session.session
            row_tasks={asyncio.create_task(self.receive()),asyncio.create_task(self.heartbeat())};self.tasks|=row_tasks;row['tasks']=row_tasks
            await self.command('scope');await row['scope'].wait()
            await self.command('wake');await self.command('advance',revision=1)
            await self.command('input',pcm=base64.b64encode(b'\x01\x00'*320).decode());await self.command('probe',revision=1)
            if fault=='asr_rst':await self.speech.asr_entered.wait()
            else:
                await row['endpoint'].wait();await self.command('seal',revision=1)
                if fault in {'plan_rst','pause_resume'}:await self.model.plan_entered.wait()
                elif fault in {'partial_rst','half_open','playback_stop'}:await row['acked'].wait()
            self.collector.record('before_network_fault')
            if fault in {'asr_rst','plan_rst','partial_rst'}:
                row['rst_applied']=relay.reset()
                if not row['rst_applied']:raise RuntimeError('rst_unavailable')
                row['status']='fault_injected'
            elif fault=='playback_stop':
                await self.command('stop',intent='network-soak-interrupt')
                await wait_pred(lambda:peer.epoch==row['epoch'] and (peer.generation is None or peer.generation.done()))
                row['status']='interrupted'
            elif fault=='half_open':
                relay.pause('up');relay.pause('down')
                await asyncio.sleep(.05) # explicitly injected finite half-open duration
                row['half_open_seconds']=.05;row['pause_observed']=relay.blocked['down'].is_set()
                if not row['pause_observed']:raise RuntimeError('half_open_not_observed')
                row['rst_applied']=relay.reset()
                if not row['rst_applied']:raise RuntimeError('rst_unavailable')
                row['status']='fault_injected'
            elif fault=='pause_resume':
                # Pause while PLAN is waiting, so real downstream ciphertext must hit the gate.
                # Queueing remains bounded; no application ACK delay is substituted.
                relay.pause('down');self.model.plan_gate.set();await relay.blocked['down'].wait()
                row['pause_observed']=relay.blocked['down'].is_set()
                await asyncio.sleep(.05);relay.resume('down');row['pause_seconds']=.05
                await row['done'].wait();row['status']='delivered' if row['delivered'] else 'failed'
            else:
                await row['done'].wait();row['status']='delivered' if row['delivered'] else 'failed'
        finally:
            self.collector.record('after_network_fault')
            self.collector.record('before_transport_cleanup')
            if row.get('peer'):
                row['heard_before_close']=len(row['peer'].session.context().get('heard',()))
                row['pending_before_close']=len(row['peer'].session.pending)
                row['game_mode']=row['peer'].session.game.get('mode')
            if row['last_ack'] is not None:self.previous_ack=row['last_ack']
            if self.ws is not None:
                # close() has the library's finite timeout; supervisor independently bounds drain.
                close_task=asyncio.create_task(self.ws.close());self.tasks.add(close_task)
                await asyncio.wait({close_task},timeout=.3)
                if not close_task.done():self.ws.transport.abort()
                row['close_handshake_confirmed']=close_task.done() and not close_task.cancelled() and close_task.exception() is None and self.ws.close_code==1000
                if fault in {'normal_close','pause_resume'} and not row['close_handshake_confirmed']:
                    row['status']='failed';row['failure']='close_unconfirmed'
            for task in row.get('tasks',()):
                if not task.done():task.cancel()
            await relay.close()
            peer=row.get('peer')
            if peer:
                try:await wait_pred(lambda:peer.run_finished,1.2)
                except TimeoutError:self.quarantined=True
                # Release ASR/PLAN late result only after the old wire scope was revoked.
                self.speech.asr_gate.set();self.model.plan_gate.set()
                confirmed,pending,errors=await drain(self.handles,time.monotonic()+.6)
                self.error_count+=errors
                row['cleanup_confirmed']=confirmed and peer.run_finished and not peer.quarantined
                row['old_heard_count']=len(peer.session.context().get('heard',()))
                row['pending_after_cleanup']=len(pending)
                row['session_cleared']=not peer.session.active and not peer.session.pending
                if not row['cleanup_confirmed']:
                    self.quarantined=True;row['status']='failed';row['failure']='cleanup_unconfirmed'
            else:self.quarantined=True
            self.ws=None;row['completed']=time.monotonic();self.collector.record('after_transport_cleanup');self.collector.record('attempt_finished')
        return self.row_report(row)
    def row_report(self,row):
        return dict(index=row['index'],fault=row['fault'],status=row['status'],frames=row['frames'],acks=row['ack_seq'],
                    cleanup_confirmed=row['cleanup_confirmed'],pending_after_cleanup=row.get('pending_after_cleanup'),
                    failure=row.get('failure'),session_cleared=row.get('session_cleared',False),old_heard_count=row.get('old_heard_count'),
                    # Identity comparison happens in memory; never serialize session IDs/ACK payloads/PCM.
                    new_session=row.get('new_session',None),old_ack_checked=row.get('old_ack_checked'),control=row['control'],
                    heard_before_close=row.get('heard_before_close'),pending_before_close=row.get('pending_before_close'),
                    game_mode=row.get('game_mode') if row.get('game_mode') in {'chat','guess','story','adventure','association'} else None,
                    started_seconds=round(row.get('started',self.started)-self.started,3),
                    completed_seconds=None if 'completed' not in row else round(row['completed']-self.started,3),
                    rst_applied=row.get('rst_applied'),relay_network_errors=row['relay'].network_errors if 'relay' in row else None,
                    pause_observed=row.get('pause_observed'),close_handshake_confirmed=row.get('close_handshake_confirmed'),
                    first_transport_ms=None if row['first_at'] is None else round((row['first_at']-row.get('started',row['first_at']))*1000,2),
                    relay_bytes=dict(row['relay'].bytes) if 'relay' in row else None,relay_buffer_observed_max=row['relay'].buffer_peak if 'relay' in row else None,
                    injected_half_open_seconds=row.get('half_open_seconds'),injected_pause_seconds=row.get('pause_seconds'))
    async def close(self):
        self.closed=True;self.allowance.open=False;deadline=time.monotonic()+1.5
        if self.ws:self.ws.transport.abort()
        for relay in self.relays:await relay.close(deadline)
        if self.server:
            self.server.close();waiter=asyncio.create_task(self.server.wait_closed());self.tasks.add(waiter)
        confirmed,pending,errors=await drain(self.handles,deadline);self.error_count+=errors
        if not confirmed or any(p.quarantined or not p.run_finished for p in self.peers):self.quarantined=True
        self.collector.record('final');self.collector.closed=True
        if self.patcher:self.patcher.stop()
        if self.loop:self.loop.set_exception_handler(self.old_exception_handler)
        if self.temp:self.temp.cleanup()
        return dict(confirmed=confirmed and not self.quarantined,pending_tasks=len(pending),errors=self.error_count,isolated=self.quarantined)

class NetworkReport(dict):
    # Not serialized: a process supervisor must own this handle if cleanup fails.
    cleanup_handle=None

async def run_tls_soak(limits=Limits(),*,seed=17,stop=None):
    """Synthetic-only: no caller-provided cloud factory or device switch."""
    limits.validate();transport=LoopbackTlsTransport(limits,seed);stop=stop or asyncio.Event()
    started=time.monotonic();deadline=started+limits.duration;attempts=[];reason='duration';cleanup=None;cancelled=False
    order=list(TEXTS);random.Random(seed).shuffle(order)
    sampler=None
    async def samples():
        while True:transport.collector.record('periodic');await asyncio.sleep(limits.sample_interval)
    try:
        await transport.start();sampler=asyncio.create_task(samples())
        index=0
        while time.monotonic()<deadline and not stop.is_set() and index<limits.max_attempts:
            target=started+index*limits.interval
            while time.monotonic()<min(target,deadline) and not stop.is_set():await asyncio.sleep(min(.05,max(0,min(target,deadline)-time.monotonic())))
            if time.monotonic()>=deadline or stop.is_set():break
            # Every fault is followed by an explicit normal recovery row before next fault.
            fault=MATRIX[(index//2)%len(MATRIX)] if index%2==0 else 'normal_close'
            task=asyncio.create_task(transport.attempt(order[index%len(order)],fault));transport.tasks.add(task)
            stopper=asyncio.create_task(stop.wait())
            done,_=await asyncio.wait({task,stopper},timeout=min(limits.attempt_timeout,max(0,deadline-time.monotonic())),return_when=asyncio.FIRST_COMPLETED)
            stopper.cancel();await asyncio.gather(stopper,return_exceptions=True)
            if task not in done:
                task.cancel();await asyncio.wait({task},timeout=1.5)
                reason='cancelled' if stop.is_set() else 'attempt_timeout'
                attempts.append(dict(index=index,fault=fault,status=reason));break
            try:row=task.result()
            except Exception:reason='attempt_failure';attempts.append(dict(index=index,fault=fault,status='failed',failure='transport_or_cleanup'));break
            attempts.append(row);index+=1
            if transport.quarantined:reason='isolated';break
            if row['status']=='failed':reason='attempt_failure';break
            if not transport.allowance.open:reason='allowance';break
        if stop.is_set():reason='cancelled'
        elif len(attempts)>=limits.max_attempts:reason='attempt_cap' # never idle to pad duration
    except asyncio.CancelledError:cancelled=True;reason='caller_cancelled'
    except Exception:reason='startup_or_transport_failure'
    finally:
        if sampler:sampler.cancel();await asyncio.gather(sampler,return_exceptions=True)
        observation_seconds=time.monotonic()-started
        cleanup=await transport.close()
    elapsed=time.monotonic()-started
    report=NetworkReport(format=1,layer='real_loopback_tls_tcp_relay_synthetic_asr_model_tts',seed=seed,
                requested_seconds=limits.duration,elapsed_seconds=round(elapsed,3),observation_seconds=round(observation_seconds,3),
                wall_60_minutes_observed=observation_seconds>=3600 and limits.duration==3600,
                active_attempt_seconds=round(sum(max(0,r.get('completed',r['started'])-r['started']) for r in transport.connections),3),stop_reason=reason,caller_cancelled=cancelled,
                attempted=len(attempts),delivered=sum(r.get('status')=='delivered' for r in attempts),
                injected_fault_attempts=sum(r.get('status')=='fault_injected' for r in attempts),
                interrupted_attempts=sum(r.get('status')=='interrupted' for r in attempts),
                failures=sum(r.get('status') not in {'delivered','fault_injected','interrupted'} for r in attempts),attempts=attempts,
                resource_collection_valid=not transport.collector.errors and cleanup['confirmed'] and bool(attempts) and all(r.get('status') in {'delivered','fault_injected','interrupted'} for r in attempts),
                connections_attempted=len(transport.connections),peers_constructed=len(transport.peers),connection_ledger=[transport.row_report(r) for r in transport.connections],
                allowance=transport.allowance.report(),asr_calls=transport.speech.asr_calls,model_stage_calls=transport.meter.stages,
                cleanup=cleanup,resource_samples=list(transport.collector.rows),resource_trends=transport.collector.summary(),
                observations=transport.collector.seen,collection_errors=transport.collector.errors,
                loop_events=list(transport.loop_events),continuous_peaks_known=False,cloud_enabled=False,device_executed=False,packets_saved=False,
                acoustic_timings=None,billing=None,full_acceptance=False,p14_verified=False,
                missing=['device_network','supplier_network','real_asr','speaker_ack','60min_effective_interaction','billing'])
    report.cleanup_handle=transport if not cleanup['confirmed'] else None
    return report
