"""Disabled-by-default sustained synthetic interaction, not A36/P14 acceptance.

Only the reviewed persistent topology, real production voice wire and relay;
no cloud/device factory, forced GC, replacement server or peer history.
"""
import argparse,asyncio,base64,json,os,secrets,signal,socket,ssl,subprocess,sys,tempfile,time
from contextlib import asynccontextmanager
from dataclasses import dataclass,asdict
from pathlib import Path
from types import SimpleNamespace as NS
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import v2_persistent_tls as p
from scripts.v2_soak import Allowance
from scripts.v2_tls_soak import SyntheticModel,SyntheticSpeech,NetworkMeter
from backend.v2.companion import UnifiedProviders

# Labels/expected witnesses remain driver-side. Only the actual synthetic text
# goes through ASR -> VoicePeer -> production plan/facts/review -> TTS/ACK.
TEXTS=('猜动物谜语吧，每次一条线索。','轮流编蓝色星星的故事，一人一句。',
       '改成每人两句，飞船只能慢慢飞。','接着讲刚才的蓝色星星。',
       '换成太空探险，我当船长，你当领航员。','交换角色，我当领航员，你当船长。',
       '轮流说红色水果，不重复。','继续说红色水果。','回到蓝色星星故事，一人一句。')
MODES=('guess','story','story','story','adventure','adventure','association','association','story')
PHASES=('input','playback','processing','idle','network','cleanup')

@dataclass(frozen=True)
class Plan:
    duration:int=3600
    connections:int=70
    turns:int=720
    model_calls:int=3600
    tts_calls:int=720
    characters:int=20000
    units:int=4320
    input_seconds:float=6.
    playback_seconds:float=2.
    sample_seconds:float=5.
    def validate(self):
        p.require(type(self.duration) is int and self.duration in (90,3600))
        p.require((self.connections,self.turns,self.model_calls,self.tts_calls,self.characters,self.units)==(70,720,3600,720,20000,4320))
        p.require((self.input_seconds,self.playback_seconds,self.sample_seconds)==(6.,2.,5.))
    @property
    def service_seconds(self):return self.duration+20

class Timeline:
    """Exclusive wall phases; effective media is counted from bytes, not sleeps."""
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.started=self.last=clock();self.phase='idle';self.wall={k:0. for k in PHASES}
        self.input_samples=0;self.sent_input_samples=0;self.played_samples=0
    def enter(self,phase):
        p.require(phase in PHASES);now=self.clock();p.require(now>=self.last)
        self.wall[self.phase]+=now-self.last;self.last=now;self.phase=phase
    def report(self):
        now=self.clock();wall=dict(self.wall);wall[self.phase]+=now-self.last
        return dict(wall_seconds=wall,elapsed_seconds=now-self.started,
                    declared_input_seconds=self.input_samples/16000,sent_input_seconds=self.sent_input_samples/16000,simulated_ack_playback_seconds=self.played_samples/24000)

class MixedModel(SyntheticModel):
    async def complete(self,instruction,data,*,schema=None):
        props=(schema or {}).get('properties',{})
        if 'mode' not in props:
            if 'facts' in props:return json.dumps(dict(facts=[dict(key='rule',value=data['text'])] if '改成' in data.get('text','') else []),ensure_ascii=False)
            return await super().complete(instruction,data,schema=schema)
        self.plan_entered.set();await self.plan_gate.wait()
        text=data.get('text');p.require(text in TEXTS);index=TEXTS.index(text);game=data.get('context',{}).get('game',{})
        # These continuations really require the last committed production state.
        if index==3:p.require(game.get('mode')=='story' and game.get('rules')=='每人两句；飞船只能慢慢飞')
        if index==5:p.require(game.get('mode')=='adventure' and game.get('roles')==['孩子是船长','瓦力是领航员'])
        if index==7:p.require(game.get('mode')=='association' and game.get('rules')=='红色水果不重复')
        rules='一人一句' if index in (1,8) else '每人两句；飞船只能慢慢飞' if index in (2,3) else '红色水果不重复' if index in (6,7) else '轮流行动'
        roles=['孩子是船长','瓦力是领航员'] if index==4 else ['孩子是领航员','瓦力是船长'] if index==5 else []
        return json.dumps(dict(action='continue' if index in (3,7) else 'change',mode=MODES[index],rules=rules,roles=roles,secrets={},
            sentences=['小飞船慢慢靠近蓝色星星。'],anchors={}),ensure_ascii=False)

class MixedSpeech(SyntheticSpeech):
    def __init__(self,allowance,plan):super().__init__(allowance);self.plan=plan
    @asynccontextmanager
    async def synthesize(self,text,rate):
        p.require(rate==24000);self.allowance.take('tts',len(text));self.tts_active+=1;self.tts_entered+=1
        async def chunks():
            # Exactly 2s PCM; driver simulates its playout before each ACK.
            for _ in range(20):yield b'\x01\x00'*2400
        try:yield chunks()
        finally:self.tts_active-=1;self.tts_exited+=1

def process_identity():
    text=Path('/proc/self/stat').read_text();ticks=int(text[text.rindex(')')+2:].split()[19])
    return dict(pid=os.getpid(),start_ticks=ticks)

class MixedService(p.Service):
    def __init__(self,plan):
        super().__init__();self.plan=plan
        self.allowance=Allowance(NS(duration=plan.service_seconds,model_units=1,tts_units=1,allowance_units=plan.units,
            model_calls=plan.model_calls,tts_calls=plan.tts_calls,tts_characters=plan.characters))
        self.speech=MixedSpeech(self.allowance,plan);self.model=MixedModel();self.meter=NetworkMeter(self.model,self.allowance)
    def state(self):
        r=super().state();peer=self.peer
        r.update(process=process_identity(),asr_active=self.speech.asr_active,tts_active=self.speech.tts_active,
                 capture_bytes=len(peer.capture) if peer else 0,recognition_active=bool(peer and peer.recognition and not peer.recognition.done()),
                 rules_hash=p.digest(peer.session.game.get('rules')) if peer else None,
                 roles_hash=p.digest(peer.session.game.get('roles')) if peer else None)
        return r
    async def dispatch(self,event):
        if event.get('op')!='mixed_configure':return await super().dispatch(event)
        p.require(not self.isolated and type(event.get('step')) is int and 0<=event['step']<len(TEXTS) and event.get('fault') in p.MATRIX)
        await p.wait_pred(lambda:not self.peer or self.finished or not self.state()['generation'])
        self.speech.text=TEXTS[event['step']];self.speech.asr_entered.clear();self.model.plan_entered.clear()
        self.speech.asr_gate.set();self.model.plan_gate.set()
        if event['fault']=='asr_rst':self.speech.asr_gate.clear()
        if event['fault'] in {'plan_rst','pause_resume'}:self.model.plan_gate.clear()
        return dict(ok=True,state=self.state())

class PacedWire(p.Wire):
    def __init__(self,*args,timeline,observe,**kw):
        super().__init__(*args,**kw);self.timeline=timeline;self.observe=observe;self.input_end=None;self.first_latency=None
    async def input(self):
        self.endpoint.clear();self.done.clear();self.acked.clear();self.delivered=False;self.turn_acks=0;self.first_at=None;self.first_latency=None
        self.revision+=1;await self.command('advance',revision=self.revision)
        await self.observe('input_started');self.timeline.enter('input');start=time.monotonic()
        for i in range(300):
            await self.command('input',pcm=base64.b64encode(b'\x01\x00'*320).decode());self.timeline.sent_input_samples+=320
            await asyncio.sleep(.02)
            self.timeline.input_samples+=320
        self.input_end=time.monotonic();p.require(self.input_end-start>=6)
        self.timeline.enter('processing');await self.observe('input_finished');await self.command('probe',revision=self.revision)
    async def before_ack(self,event):
        pcm=base64.b64decode(event['pcm'],validate=True);p.require(0<len(pcm)<=4800 and len(pcm)%2==0 and event['end']-event['start']==len(pcm)//2)
        if self.first_latency is None:
            self.first_latency=(self.first_at if self.first_at is not None else time.monotonic())-self.input_end;await self.observe('first_audio_transport')
        self.timeline.enter('playback');await asyncio.sleep(len(pcm)/48000)
    async def after_ack(self,event):
        self.timeline.played_samples+=event['end']-event['start'];self.timeline.enter('processing')

class MixedDriver:
    def __init__(self,ipc,tls,port,plan,report,save):
        self.ipc=ipc;self.tls=tls;self.port=port;self.plan=plan;self.report=report;self.save=save
        self.timeline=Timeline();self.started=self.timeline.started;self.old_ack=None;self.current=None;self.turn_count=0;self.sample_error=False
    async def observe(self,event):
        p.require(len(self.report['samples'])<8192)
        state=(await self.ipc.call('state'))['state'];r=dict(event=event,connection_index=len(self.report['connections'])-1,turn_index=len(self.report['turns'])-1,elapsed=time.monotonic()-self.started,service_process=state['process'],client_process=process_identity(),
            service_resources=state['resources'],client_resources=p.scalar_resources(),pending=state['pending'],retired=state['retired'],generation=state['generation'],asr_active=state['asr_active'],tts_active=state['tts_active'],capture_bytes=state['capture_bytes'],allowance=state['allowance'])
        self.report['samples'].append(r)
    async def periodic(self):
        try:
            while True:await self.observe('periodic');self.save();await asyncio.sleep(self.plan.sample_seconds)
        except asyncio.CancelledError:raise
        except Exception:self.sample_error=True;self.report['collection_errors']+=1
    async def turn(self,wire,step,fault='normal_close'):
        p.require(self.turn_count<self.plan.turns and not self.sample_error);self.turn_count+=1
        row=dict(index=self.turn_count-1,step=step,fault=fault,status='attempted',elapsed=time.monotonic()-self.started,frame_start=wire.frames,ack_start=wire.acks)
        self.report['turns'].append(row);input_before=self.timeline.input_samples;row['playback_start_samples']=self.timeline.played_samples;played_before=self.timeline.played_samples;before=(await self.ipc.call('state'))['state'];frames=wire.frames;acks=wire.acks
        await self.ipc.call('mixed_configure',step=step,fault=fault);wire.fault=fault
        try:
            async with asyncio.timeout(15):
                await wire.input()
                if fault=='asr_rst':await self.ipc.call('entered',stage='asr')
                else:
                    await wire.seal()
                    if fault in {'plan_rst','pause_resume'}:await self.ipc.call('entered',stage='plan')
                    elif fault in {'partial_rst','half_open','playback_stop'}:await wire.acked.wait()
                if fault=='normal_close':await wire.done.wait();p.require(wire.delivered)
                # Remaining fault is performed by connection owner, using its real relay.
            row.update(status='ready_fault' if fault!='normal_close' else 'delivered',frames=wire.frames-frames,acks=wire.acks-acks,first_audio_seconds=wire.first_latency)
            if fault=='normal_close':
                state=(await self.ipc.call('state'))['state'];p.require(state['same_session'] is True and state['binding']==before['binding'] and state['game']==MODES[step] and not state['pending_audio'])
                if before['played_anchor']:p.require(state['played_anchor']==before['played_anchor'])
                row.update(binding=state['binding'],played_anchor=state['played_anchor'],played_count=state['played_count'],state_hash=state['state_hash'],rules_hash=state['rules_hash'],roles_hash=state['roles_hash'])
                await self.observe('turn_delivered')
        except BaseException:
            row['status']='incomplete';raise
        finally:
            row.update(input_seconds=(self.timeline.input_samples-input_before)/16000,playback_seconds=(self.timeline.played_samples-played_before)/24000,completed=time.monotonic()-self.started)
            self.save()
    async def connection(self,index):
        p.require(index<self.plan.connections)
        fault=p.MATRIX[(index//2+1)%7] if index%2==0 else 'normal_close'
        row=dict(index=index,round=index//14,slot=index%14,fault=fault,status='attempted',started=time.monotonic()-self.started,turn_start=len(self.report['turns']),cleanup_confirmed=False)
        self.report['connections'].append(row);relay=p.TcpRelay(self.port);wire=None;ws=None;tasks=set();self.current=(relay,tasks)
        try:
            port=await relay.start()
            ws=await p.connect(f'wss://127.0.0.1:{port}/v2/voice',ssl=self.tls,server_hostname='localhost',additional_headers={'Authorization':'Bearer '+p.TOKEN},max_size=16000,max_queue=4,write_limit=16000,close_timeout=.2,open_timeout=2)
            wire=PacedWire(ws,self.ipc,'normal_close',self.old_ack,timeline=self.timeline,observe=self.observe)
            tasks={asyncio.create_task(wire.receive()),asyncio.create_task(wire.heartbeat())};self.current=(relay,tasks)
            await wire.command('scope');await wire.scope.wait();await wire.command('wake')
            initial=(await self.ipc.call('state'))['state'];row['binding']=initial['binding'];row['new_session']=initial['new_session'];p.require(initial['new_session'] is True)
            # Seven completed turns exercise state, rule and role transitions.
            for step in range(7):await self.turn(wire,step)
            before=(await self.ipc.call('state'))['state'];row['cross_connection_old_ack_checked']=wire.old_checked
            await self.turn(wire,7,'playback_stop');await wire.command('stop',intent='mixed-interrupt');await self.ipc.call('barrier',seq=wire.seq-1)
            await self.ipc.call('mixed_configure',step=7,fault='normal_close')
            stopped=(await self.ipc.call('state'))['state'];p.require(stopped['played_count']==before['played_count'] and stopped['pending_audio']==0 and stopped['binding']==row['binding'])
            self.report['turns'][-1].update(status='interrupted',no_partial_commit=True)
            wire.old_ack=wire.last_ack;wire.old_checked=None
            await self.observe('stop_confirmed');await self.turn(wire,7);p.require(wire.old_checked is True)
            # The fixed real network matrix occurs after meaningful same-session work.
            before_fault=(await self.ipc.call('state'))['state'];await self.turn(wire,8,fault)
            self.timeline.enter('network');row.update(rst_applied=None,pause_observed=None)
            if fault in {'asr_rst','plan_rst','partial_rst'}:row['rst_applied']=relay.reset();p.require(row['rst_applied'])
            elif fault=='half_open':
                relay.pause('up');relay.pause('down');await asyncio.wait_for(relay.blocked['down'].wait(),.5)
                row['pause_observed']=True;await asyncio.sleep(.05);row['rst_applied']=relay.reset();p.require(row['rst_applied'])
            elif fault=='pause_resume':
                relay.pause('down');await self.ipc.call('unblock');await asyncio.wait_for(relay.blocked['down'].wait(),.5)
                row['pause_observed']=True;await asyncio.sleep(.05);relay.resume('down');await wire.done.wait();p.require(wire.delivered)
            elif fault=='playback_stop':await wire.command('stop',intent='mixed-network-stop');await self.ipc.call('barrier',seq=wire.seq-1)
            self.timeline.enter('processing')
            final=(await self.ipc.call('state'))['state'];p.require(final['same_session'] is True and final['binding']==row['binding'])
            last=self.report['turns'][-1];last.update(frames=wire.frames-last['frame_start'],acks=wire.acks-last['ack_start'],first_audio_seconds=wire.first_latency,playback_seconds=(self.timeline.played_samples-last['playback_start_samples'])/24000,completed=time.monotonic()-self.started)
            self.report['turns'][-1]['status']='interrupted' if fault=='playback_stop' else 'fault_injected' if fault in {'asr_rst','plan_rst','partial_rst','half_open'} else 'delivered'
            if row['fault']=='playback_stop':
                p.require(final['pending_audio']==0 and final['played_count']==before_fault['played_count']);last['no_partial_commit']=True
            if last['status']=='delivered':last.update(binding=final['binding'],played_anchor=final['played_anchor'],played_count=final['played_count'],state_hash=final['state_hash'],rules_hash=final['rules_hash'],roles_hash=final['roles_hash'])
            row.update(status=self.report['turns'][-1]['status'],new_session=initial['new_session'],frames=wire.frames,acks=wire.acks,old_ack_checked=wire.old_checked,context_hash=final['state_hash'])
        except BaseException:
            row['status']='incomplete';raise
        finally:
            self.timeline.enter('cleanup')
            try:await self.observe('before_cleanup')
            except Exception:self.sample_error=True;self.report['collection_errors']+=1
            if ws:
                closer=asyncio.create_task(ws.close());tasks.add(closer);await asyncio.wait({closer},timeout=.3)
                if not closer.done():ws.transport.abort()
                row['normal_close_confirmed']=closer.done() and not closer.cancelled() and closer.exception() is None and ws.close_code==1000
            for task in tasks:
                if not task.done():task.cancel()
            relay_ok,pending,errors=await relay.close(time.monotonic()+.6)
            ok,left,client_errors=await p.drain(lambda:tasks|relay.tasks,time.monotonic()+.6)
            unexpected=[t for t in tasks|relay.tasks if t.done() and not t.cancelled() and t.exception() is not None and not isinstance(t.exception(),p.ConnectionClosed)]
            row.update(client_cleanup=relay_ok and not pending and not left and not errors and not unexpected,relay_bytes=dict(relay.bytes),relay_buffer_peak=relay.buffer_peak)
            if wire:self.old_ack=wire.last_ack or self.old_ack
            released=(await self.ipc.call('release',allow_failure=True))['state'];row['release']=released
            row['cleanup_confirmed']=row['client_cleanup'] and released['cleanup_confirmed'] and released['transport_closed']
            row['turn_end']=len(self.report['turns']);row['completed']=time.monotonic()-self.started;self.save();p.require(row['cleanup_confirmed'])
            self.current=None
            try:await self.observe('after_cleanup')
            except Exception:self.sample_error=True;self.report['collection_errors']+=1
            self.timeline.enter('idle');p.require(not self.sample_error)

async def run_driver(args,plan,authority):
    output=args.output;report=dict(format=1,source_sha=args.source,authority=authority,layer='paced_synthetic_mixed_tls',duration=plan.duration,status='failed_or_unknown',
        limits=asdict(plan),collection_errors=0,cloud=False,device=False,acoustic=False,acceptance=False,gc_forced=False,cleanup_confirmed=False,forced_exit=False,connections=[],turns=[],samples=[],rounds=[],timing=None)
    driver=None;ipc=None;process=None;sampler=None
    def save():
        if driver:report['timing']=driver.timeline.report()
        (output/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    save()
    try:
        with tempfile.TemporaryDirectory(prefix='mixed-tls-') as folder:
            root=Path(folder)
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost','-keyout',str(root/'key'),'-out',str(root/'cert')],check=True,timeout=5,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            a,b=socket.socketpair()
            try:
                command=[sys.executable,'-I','-B',str(Path(__file__).resolve()),'_service','--enable','--duration',str(plan.duration),'--fd',str(b.fileno()),'--cert',str(root/'cert'),'--key',str(root/'key'),
                    '--lock-fd',str(args.lock_fd),'--supervisor-pid',str(args.supervisor_pid),'--parent-pid',str(os.getpid()),'--driver-pid',str(os.getpid()),'--source',args.source,'--run-id',args.run_id]
                process=subprocess.Popen(command,pass_fds=(b.fileno(),args.lock_fd),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            finally:b.close()
            ipc=await p.channel(a.detach());hello=await ipc.receive();p.require(hello['pid']==process.pid and hello['authority']==authority and hello['protocol']==p.CONTRACT)
            driver=MixedDriver(ipc,ssl.create_default_context(cafile=root/'cert'),hello['port'],plan,report,save);report.update(service_pid=process.pid,driver_pid=os.getpid())
            await driver.observe('before_warmup');sampler=asyncio.create_task(driver.periodic())
            try:
                window=asyncio.timeout(plan.duration)
                async with window:
                    index=0
                    while True:
                        p.require(not driver.sample_error);await driver.connection(index);index+=1
                        if index==1:await driver.observe('after_warmup')
                        await driver.observe('after_block')
                        if index%14==0:
                            report['rounds'].append(dict(index=index//14-1,connection_start=index-14,connection_end=index,turn_start=report['connections'][index-14]['turn_start'],turn_end=len(report['turns'])))
                            await driver.observe('round_completed')
                        save()
            except TimeoutError:
                p.require(window.expired() and time.monotonic()-driver.started>=plan.duration and not driver.sample_error)
                # Only the last in-flight attempt may be an explicit planned cutoff.
                if report['turns'] and report['turns'][-1]['status']=='incomplete':report['turns'][-1]['status']='duration_cutoff'
                if report['connections'] and report['connections'][-1]['status']=='incomplete':report['connections'][-1]['status']='duration_cutoff'
            sampler.cancel();await asyncio.wait({sampler},timeout=.5);p.require(sampler.done());sampler.result() if not sampler.cancelled() else None
            p.require(not driver.sample_error);await driver.observe('final');report['shutdown']=(await ipc.call('shutdown'))['state']
            async with asyncio.timeout(2):
                while process.poll() is None:await asyncio.sleep(.01)
            p.require(process.returncode==0);report.update(status='duration_collected_not_acceptance',cleanup_confirmed=True,service_exit=0)
    except BaseException as error:report['failure_kind']='cancelled' if isinstance(error,asyncio.CancelledError) else 'timeout' if isinstance(error,TimeoutError) else 'unconfirmed'
    finally:
        if sampler and not sampler.done():sampler.cancel();await asyncio.wait({sampler},timeout=.5)
        if ipc:ipc.writer.close()
        if process and process.poll() is None:
            process.kill();process.wait(timeout=2);report.update(forced_exit=True,cleanup_confirmed=False,status='failed_or_unknown')
        save()
    return report

def validate_shutdown(state,rows,identity):
    """Service.state() after every admitted peer's confirmed release, not a
    fabricated count of attempts. Existing report validation requires a distinct
    measured binding per admitted row, including a final duration cutoff.
    """
    p.require(type(state) is dict and state['finished'] is True)
    for key in ('active','quarantined','generation','same_session','recognition_active'):
        p.require(state[key] is False)
    for key in ('pending','retired','errors','heard','pending_audio','played_count','capture_bytes','asr_active','tts_active'):
        p.require(type(state[key]) is int and state[key]==0)
    for key in ('binding','played_anchor','state_hash','game','rules_hash','roles_hash'):
        p.require(state[key] is None)
    constructed=0
    for row in rows:
        release=row['release']
        p.require(type(release['constructed']) is int and release['constructed']==constructed+1 and release['finished'] is True)
        p.require(release['binding']==row['binding'] and release['same_session'] is True)
        constructed=release['constructed']
    p.require(type(state['constructed']) is int and state['constructed']==constructed and state['process']==identity)


def _validate_report(report,plan):
    p.require('failure_kind' not in report)
    p.require(report['limits']==asdict(plan) and report['duration']==plan.duration and type(report['collection_errors']) is int and report['collection_errors']==0)
    p.require(report['status']=='duration_collected_not_acceptance' and report['cleanup_confirmed'] is True and report['forced_exit'] is False and type(report['service_exit']) is int and report['service_exit']==0)
    p.require(all(report[k] is False for k in ('cloud','device','acoustic','acceptance','gc_forced')))
    rows=report['connections'];turns=report['turns'];samples=report['samples'];p.require(0<len(rows)<=plan.connections and 0<len(turns)<=plan.turns and 0<len(samples)<=8192)
    bindings=set();previous_end=0;previous_time=0.
    for index,row in enumerate(rows):
        p.require(type(row['started']) in (int,float) and type(row['completed']) in (int,float) and previous_time<=row['started']<=row['completed']);previous_time=row['completed']
        p.require(row['turn_start']==previous_end and row['turn_end']>previous_end and row['turn_end']<=len(turns));previous_end=row['turn_end']
        p.require(p.hex_string(row.get('binding'),64) and row['binding'] not in bindings);bindings.add(row['binding'])
        p.require(row['fault']==(p.MATRIX[(index//2+1)%7] if index%2==0 else 'normal_close'))
        p.require(row['index']==index and row['cleanup_confirmed'] is True and row['client_cleanup'] is True and row['release']['cleanup_confirmed'] is True and row['release']['transport_closed'] is True and row['release']['active'] is False and row['release']['quarantined'] is False)
        p.require(all(type(row['release'][k]) is int and row['release'][k]==0 for k in ('pending','retired','errors','heard','pending_audio')))
        p.require(row['status'] in {'delivered','fault_injected','interrupted','duration_cutoff'})
        if row['status']=='duration_cutoff':p.require(index==len(rows)-1)
        else:
            p.require(row['cross_connection_old_ack_checked'] is True if index>0 else row['cross_connection_old_ack_checked'] is None)
            p.require(row['turn_end']-row['turn_start']==10)
            last=turns[row['turn_end']-1]
            if row['fault'] in {'asr_rst','plan_rst'}:p.require(last['frames']==last['acks']==0)
            elif row['fault'] in {'partial_rst','half_open','playback_stop'}:p.require(last['frames']>=last['acks']==1)
            else:p.require(last['frames']==last['acks'] and last['acks']>0)
            p.require(row['new_session'] is True and row['frames']>=row['acks']>0 and row['old_ack_checked'] is True)
            if row['fault'] in {'asr_rst','plan_rst','partial_rst','half_open'}:p.require(row['rst_applied'] is True)
            if row['fault'] in {'pause_resume','half_open'}:p.require(row['pause_observed'] is True)
    completed=len(rows)-(rows[-1]['status']=='duration_cutoff');rounds=report['rounds'];p.require(len(rounds)==completed//14)
    for index,r in enumerate(rounds):
        start=index*14;end=start+14
        p.require(r==dict(index=index,connection_start=start,connection_end=end,turn_start=rows[start]['turn_start'],turn_end=rows[end-1]['turn_end']))
    p.require(previous_end==len(turns))
    for index,row in enumerate(turns):
        p.require(row['index']==index and row['status'] in {'delivered','fault_injected','interrupted','duration_cutoff'})
        if row['status']=='duration_cutoff':p.require(index==len(turns)-1)
        if row['status']=='delivered':p.require(type(row['first_audio_seconds']) in (int,float) and 0<=row['first_audio_seconds']<=15);p.require(row['frames']==row['acks'] and row['acks']>0 and p.hex_string(row['binding'],64) and p.hex_string(row['played_anchor'],64))
        if row['status']=='interrupted':p.require(row['no_partial_commit'] is True)
        p.require(0<=row['input_seconds']<=6 and 0<=row['playback_seconds']<=2.01)
    identities={json.dumps(row['service_process'],sort_keys=True) for row in samples};p.require(len(identities)==1)
    previous=-1
    for sample in samples:
        p.require(sample['elapsed']>=previous);previous=sample['elapsed'];p.require(sample['service_process']['pid']==report['service_pid'] and sample['client_process']['pid']==report['driver_pid'] and report['service_pid']!=report['driver_pid'])
        for key in ('service_process','client_process'):p.require(sample[key].keys()=={'pid','start_ticks'} and all(type(v) is int and v>0 for v in sample[key].values()))
        for key in ('service_resources','client_resources'):p.require(sample[key].keys()=={'backend_rss_bytes','backend_fds','backend_threads','asyncio_tasks'} and all(type(v) is int and v>0 for v in sample[key].values()))
    periodic=[s['elapsed'] for s in samples if s['event']=='periodic']
    p.require(len(periodic)>=3 and periodic[0]<=5 and periodic[-1]>=plan.duration-10 and all(b-a<=10 for a,b in zip(periodic,periodic[1:])))
    p.require(samples[0]['event']=='before_warmup' and samples[-1]['event']=='final' and any(s['event']=='after_warmup' for s in samples))
    final_allowance=report['shutdown']['allowance'];p.require(final_allowance['account_quota_known'] is False and final_allowance['bill_cny'] is None)
    for key,cap in (('model_calls',plan.model_calls),('tts_calls',plan.tts_calls),('tts_unicode_characters',plan.characters),('reserved_units',plan.units)):
        values=[s['allowance'][key] for s in samples]+[final_allowance[key]]
        p.require(all(type(v) is int and 0<=v<=cap for v in values) and values==sorted(values))
    warmup=[s for s in samples if s['event']=='after_warmup'];p.require(len(warmup)==1 and warmup[0]['elapsed']>=rows[0]['completed'])
    timing=report['timing'];p.require(timing['elapsed_seconds']>=plan.duration and abs(sum(timing['wall_seconds'].values())-timing['elapsed_seconds'])<.01)
    p.require(timing['declared_input_seconds']>0 and timing['simulated_ack_playback_seconds']>0 and timing['wall_seconds']['input']>=timing['declared_input_seconds'] and timing['wall_seconds']['playback']>=timing['simulated_ack_playback_seconds'])
    p.require(abs(sum(r['input_seconds'] for r in turns)-timing['declared_input_seconds'])<.001 and abs(sum(r['playback_seconds'] for r in turns)-timing['simulated_ack_playback_seconds'])<.001)
    validate_shutdown(report['shutdown'],rows,samples[-1]['service_process'])


def validate_report(report,plan):
    try:return _validate_report(report,plan)
    except (KeyError,TypeError,IndexError,ValueError):raise p.Rejected('mixed_report_invalid') from None


def supervise(output,plan):
    plan.validate();output=Path(output).resolve()
    with p.heavy_lock() as fd:
        info=os.fstat(fd);output.mkdir(exist_ok=False);source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).resolve().parents[1],timeout=2,text=True).strip();run_id=secrets.token_hex(16)
        command=[sys.executable,'-I','-B',str(Path(__file__).resolve()),'_driver','--enable','--duration',str(plan.duration),'--output',str(output),'--lock-fd',str(fd),'--supervisor-pid',str(os.getpid()),'--parent-pid',str(os.getpid()),'--source',source,'--run-id',run_id]
        child=subprocess.Popen(command,pass_fds=(fd,),start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            code=child.wait(timeout=plan.duration+40)
            path=output/'result.json';p.require(path.is_file() and not path.is_symlink() and path.stat().st_size<16*1024*1024)
            report=json.loads(path.read_bytes());validate_report(report,plan)
            p.require(code==0 and report['source_sha']==source and report['authority']==dict(source_sha=source,run_digest=p.digest(run_id),lock_identity=p.digest([info.st_dev,info.st_ino])))
        except BaseException:
            if child.poll() is None:os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=2)
            (output/'supervisor.json').write_text(json.dumps(dict(status='failed_or_unknown',cleanup_confirmed=False,no_retry=True))+'\n');raise p.Rejected('mixed_failed') from None
        (output/'supervisor.json').write_text(json.dumps(dict(status='validated_not_acceptance',exit_code=code,no_retry=True))+'\n');return report

def cli(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=('prepare','_driver','_service'));parser.add_argument('--enable',action='store_true')
    parser.add_argument('--duration',type=int,choices=(90,3600),default=3600);parser.add_argument('--output',type=Path)
    for field in ('fd','lock-fd','supervisor-pid','parent-pid','driver-pid'):parser.add_argument('--'+field,type=int)
    for field in ('cert','key','source','run-id'):parser.add_argument('--'+field)
    args=parser.parse_args(argv)
    if not args.enable:return 2
    try:
        plan=Plan(duration=args.duration);plan.validate()
        if args.mode=='prepare':supervise(args.output,plan)
        else:
            with p.internal_authority(args,program=__file__) as authority:
                if args.mode=='_service':asyncio.run(p.serve_child(args.fd,args.cert,args.key,authority,factory=lambda:MixedService(plan),lifetime=plan.service_seconds))
                else:
                    r=asyncio.run(run_driver(args,plan,authority));return 0 if r['cleanup_confirmed'] else 2
        return 0
    except BaseException:return 2

if __name__=='__main__':raise SystemExit(cli())
