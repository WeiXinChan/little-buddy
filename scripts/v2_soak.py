"""A36 preparation: real VoicePeer, synthetic text and JSON duplex/ACK client.

No credentials, device launcher, or default cloud provider. Wall time is monotonic;
short fixture runs cannot satisfy 3600s. External providers require -- API consent.
"""
import asyncio
from collections import deque
from copy import deepcopy
from contextlib import asynccontextmanager
from dataclasses import asdict,dataclass,replace
import json
from pathlib import Path
import time
from backend.v2.voice import VoicePeer,VoiceFault,WireError
from backend.v2.companion import UnifiedProviders,CompanionPolicy
from scripts.v2_multiturn_probe import BatchState,ProbeLimit,usage_delta

@dataclass(frozen=True)
class Limits:
    duration:float=3600
    interval:float=30
    sample_interval:float=30
    attempt_timeout:float=40
    max_attempts:int=120
    model_calls:int=720
    tts_calls:int=240
    tts_characters:int=28800
    allowance_units:int=960
    model_units:int=1
    tts_units:int=1
    def validate(self):
        for name in ('duration','interval','sample_interval','attempt_timeout'):
            value=getattr(self,name)
            if type(value) not in (int,float) or not 0<value<=3660:raise ValueError('limits')
        for name in ('max_attempts','model_calls','tts_calls','tts_characters','allowance_units','model_units','tts_units'):
            value=getattr(self,name)
            if type(value) is not int or not 1<=value<=1000000000:raise ValueError('limits')
        if self.duration>3600 or self.attempt_timeout>45 or self.max_attempts>120 or self.model_calls>720 or self.tts_calls>240 or self.tts_characters>28800 or self.duration/self.sample_interval>4095:raise ValueError('limits')

@dataclass(frozen=True)
class CloudBudget:
    # Root must review worst-case request bounds against its actual provider.
    max_micro_cny:int
    model_request_micro_cny:int
    tts_request_micro_cny:int
    reviewed_bounds:bool=False
    def validate(self):
        if self.reviewed_bounds is not True or any(type(v) is not int or v<=0 for v in
             (self.max_micro_cny,self.model_request_micro_cny,self.tts_request_micro_cny)):
            raise ProbeLimit('cloud_budget_not_reviewed')

# Fixed synthetic material; expectations are not sent to providers.
SCENARIOS=(
 ('guess','你出动物谜语我猜，每次一条线索。','normal'),
 ('story','不猜了，我们轮流编小猫坐飞船的故事。','normal'),
 ('adventure','改成太空探险，我当船长，你当领航员。','interrupt'),
 ('association','轮流说红色水果，不重复，我先说草莓。','delay'),
 ('story','继续编小猫飞船的故事，飞船只能慢慢飞。','drop'),
 ('chat','不玩了，聊聊云的形状。','normal'),
)

class Allowance:
    def __init__(self,limits):self.limits=limits;self.open=True;self.model=0;self.tts=0;self.characters=0;self.units=0;self.expires=time.monotonic()+limits.duration
    def take(self,kind,characters=0):
        if not self.open or time.monotonic()>=self.expires:raise ProbeLimit('closed')
        l=self.limits;charge=l.model_units if kind=='model' else l.tts_units
        if (self.units+charge>l.allowance_units or
            kind=='model' and self.model>=l.model_calls or
            kind=='tts' and (self.tts>=l.tts_calls or self.characters+characters>l.tts_characters)):
            self.open=False;raise ProbeLimit('allowance')
        self.units+=charge
        if kind=='model':self.model+=1
        else:self.tts+=1;self.characters+=characters
    def report(self):return dict(model_calls=self.model,tts_calls=self.tts,tts_unicode_characters=self.characters,reserved_units=self.units,account_quota_known=False,bill_cny=None)

class MeterModel:
    def __init__(self,inner,allowance):self.inner=inner;self.allowance=allowance;self.stages={};self.failures=0
    async def complete(self,instruction,data,*,schema=None):
        self.allowance.take('model') # reserve including failures/retries, before await
        if len(instruction.encode())>32768 or len(json.dumps(data,ensure_ascii=False).encode())>32768:raise ProbeLimit('request_size')
        props=schema.get('properties',{}) if isinstance(schema,dict) else {}
        stage='plan' if 'mode' in props else 'facts' if 'facts' in props else 'safe' if 'allow' in props else 'compact'
        self.stages[stage]=self.stages.get(stage,0)+1
        try:return await self.inner.complete(instruction,data,schema=schema)
        except BaseException as error:
            self.failures+=1
            if getattr(error,'code',None)=='quota':self.allowance.open=False
            raise

class MeterSpeech:
    def __init__(self,inner,allowance):self.inner=inner;self.allowance=allowance
    def synthesize(self,text,rate):
        self.allowance.take('tts',len(text));return self.inner.synthesize(text,rate)
    def recognize(self,*args):raise ProbeLimit('asr_not_supported')

class Duplex:
    """Bounded JSON transport. Delay/drop affect simulated downstream ACKs."""
    def __init__(self):self.incoming=asyncio.Queue(8);self.outgoing=asyncio.Queue(8);self.closed=False
    async def recv(self):return await self.incoming.get()
    async def send(self,raw):
        if self.closed:raise ProbeLimit('transport_closed')
        await self.outgoing.put(raw)
    async def close(self,*args):self.closed=True

class AttemptFailure(ProbeLimit):
    def __init__(self,stage,reason):super().__init__('attempt_failed');self.stage=stage;self.reason=reason

FAILURE_STAGES=frozenset({'admission','bind','first_audio','stop','generation','delivery','attempt_wait'})
FAILURE_REASONS=frozenset({'session_closed','transport_closed','timeout','cancelled','quota','wire','limit','provider','unknown'})
def failure_metadata(error=None,*,stage='attempt_wait',reason='unknown',transport=None):
    if isinstance(error,AttemptFailure):stage,reason=error.stage,error.reason
    result=dict(stage=stage if stage in FAILURE_STAGES else 'attempt_wait',reason=reason if reason in FAILURE_REASONS else 'unknown')
    if transport is not None:
        result.update(peer_closed=bool(transport.peer.closed),session_active=bool(transport.peer.session.active),
                      response_expired=bool(transport.peer.session.response_expired),control=transport.last_control)
    return result

class BackendTransport:
    def __init__(self,providers):
        self.socket=Duplex();self.peer=VoicePeer(self.socket,providers,CompanionPolicy())
        self.epoch=0;self.seq=0;self.lock=asyncio.Lock();self.tasks=set();self.failed=False;self.mode='normal'
        self.first=asyncio.Event();self.completed=asyncio.Event();self.identity=None;self.ack_seq=0;self.frames=0;self.first_at=None;self.last_control=None;self.failure_stage='admission'
    def start(self):
        self.tasks={asyncio.create_task(self.peer.run()),asyncio.create_task(self.receive()),asyncio.create_task(self.heartbeat())}
        for task in self.tasks:task.add_done_callback(lambda done:None if done.cancelled() else done.exception())
    async def command(self,kind,**fields):
        async with self.lock:
            if kind=='stop':self.epoch+=1;self.seq=0
            raw=json.dumps(dict(v=2,type=kind,epoch=self.epoch,seq=self.seq,**fields));self.seq+=1
            await self.socket.incoming.put(raw)
    async def heartbeat(self):
        while True:
            await self.command('heartbeat');await asyncio.sleep(5)
    async def receive(self):
        while True:
            event=json.loads(await self.socket.outgoing.get());kind=event['type']
            if event.get('epoch')!=self.epoch:continue
            if kind=='bound':self.identity=event['identity'];self.ack_seq=0
            if kind=='failure':
                self.last_control=event.get('code') if event.get('code') in {'voice','timeout','network','quota','safety'} else 'unknown'
                self.failed=True;self.completed.set()
            if kind=='reply_end':self.completed.set()
            if kind=='audio':
                self.frames+=1;self.first_at=self.first_at or time.monotonic();self.first.set()
                if self.mode in {'interrupt','drop'}:continue
                if self.mode=='delay':await asyncio.sleep(.15)
                identity=dict(self.identity,sequence=self.ack_seq);self.ack_seq+=1
                await self.command('ack',identity=identity,player=event['player'],stream=event['stream'],segment=event['segment'],head=event['end'])
    async def attempt(self,text,mode):
        self.failure_stage='admission'
        try:return await self._attempt(text,mode)
        except Exception as error:
            reason='session_closed' if isinstance(error,ProbeLimit) and error.args==('session_closed',) else 'timeout' if isinstance(error,TimeoutError) else 'wire' if isinstance(error,WireError) else 'quota' if isinstance(error,VoiceFault) and error.code=='quota' else 'limit' if isinstance(error,ProbeLimit) else 'provider'
            raise AttemptFailure(self.failure_stage,reason) from None

    async def _attempt(self,text,mode):
        if self.peer.closed or not self.peer.session.active:raise ProbeLimit('session_closed')
        self.mode=mode;self.first.clear();self.completed.clear();self.failed=False;self.first_at=None;self.frames=0;self.last_control=None
        self.peer.session.begin_turn();await self.peer.commands() # synthetic ASR/endpoint boundary
        generation=asyncio.create_task(self.peer.respond(text,self.peer.epoch));self.peer.generation=generation
        self.failure_stage='bind'
        await self.command('bind',player='soak-'+str(self.peer.session.turn))
        if mode in {'interrupt','drop'}:
            self.failure_stage='first_audio'
            await self.first.wait()
            self.failure_stage='stop'
            await self.command('stop',intent='soak-stop') # real protocol revocation, no direct ACK/state edit
        self.failure_stage='generation'
        try:await asyncio.shield(generation)
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling() or mode not in {'interrupt','drop'} or not generation.cancelled():raise
        if mode in {'interrupt','drop'}:
            # Stop command must actually be processed, not just enqueued.
            while self.peer.epoch!=self.epoch:await asyncio.sleep(.001)
        else:
            self.failure_stage='delivery';await self.completed.wait()
        return dict(delivered=not self.failed and self.completed.is_set(),frames=self.frames,
                    game_mode=self.peer.session.game.get('mode') if self.peer.session.game.get('mode') in {'chat','guess','story','adventure','association'} else None,
                    first_transport_at=self.first_at,interrupted=mode in {'interrupt','drop'} and self.peer.epoch==self.epoch)
    def sample(self):
        return dict(active_sessions=int(self.peer.session.active),active_operations=len(self.peer.generation_scopes),
                    retired_pending=sum(not t.done() for t in self.peer.retired_tasks),
                    generation_pending=int(self.peer.generation is not None and not self.peer.generation.done()),
                    transport_tasks_pending=sum(not t.done() for t in self.tasks))
    async def close(self):
        self.peer.closed=True;self.socket.closed=True;self.peer.session.clear();self.peer.invalidate_visual()
        tasks=self.tasks|set(self.peer.retired_tasks)
        if self.peer.generation:tasks.add(self.peer.generation)
        for task in tasks:task.cancel()
        if tasks:
            try:await asyncio.wait(tasks,timeout=.6)
            except asyncio.CancelledError:pass
        pending={t for t in tasks|set(self.peer.retired_tasks) if not t.done()}
        return not pending and not self.peer.quarantined,pending

class OfflineModel:
    async def complete(self,instruction,data,*,schema=None):
        if '提取孩子' in instruction:return '{"facts":[]}'
        if '审核下一个' in instruction:return '{"allow":true}'
        if '只返回JSON {"keep"' in instruction:return '{"keep":[]}'
        text=data.get('text','');mode='story' if '故事' in text else 'guess' if '谜语' in text else 'adventure' if '探险' in text else 'association' if '水果' in text else 'chat'
        return json.dumps(dict(action='change',mode=mode,rules='合成轮流规则',roles=[],secrets={},sentences=['小猫慢慢出发。'],anchors={}),ensure_ascii=False)

class OfflineSpeech:
    @asynccontextmanager
    async def synthesize(self,text,rate):
        async def frames():
            yield b'\x01\x00'*2400;await asyncio.sleep(.005);yield b'\x01\x00'*2400
        yield frames()

def resources():
    try:
        status=Path('/proc/self/status').read_text().splitlines()
        return dict(backend_rss_bytes=next(int(s.split()[1])*1024 for s in status if s.startswith('VmRSS:')),
                    backend_threads=next(int(s.split()[1]) for s in status if s.startswith('Threads:')),
                    backend_fds=len(list(Path('/proc/self/fd').iterdir())),asyncio_tasks=len(asyncio.all_tasks()),device_rss_bytes=None)
    except (OSError,StopIteration,ValueError):return dict(backend_rss_bytes=None,backend_threads=None,backend_fds=None,asyncio_tasks=len(asyncio.all_tasks()),device_rss_bytes=None)

class ObservedScopes(dict):
    """Same mapping semantics; snapshot AFTER the real production mutation."""
    def __init__(self,values,capture):super().__init__(values);self.capture=capture
    def __setitem__(self,key,value):
        super().__setitem__(key,value);self.capture('operation_started')
    def pop(self,key,*default):
        result=super().pop(key,*default);self.capture('operation_finished');return result

class ObservedRetired(set):
    def __init__(self,values,capture):super().__init__(values);self.capture=capture
    def add(self,value):super().add(value);self.capture('retired_added')
    def discard(self,value):super().discard(value);self.capture('retired_removed')

class ResourceCollector:
    PHASES=frozenset({'initial','periodic','operation_started','operation_finished','retired_added','retired_removed','attempt_started','attempt_finished','before_attempt_cancel','after_attempt_cancel','before_transport_cleanup','after_transport_cleanup','after_owner_cleanup','final'})
    KEYS=('backend_rss_bytes','backend_fds','backend_threads','asyncio_tasks','retired_pending','active_operations','generation_pending','transport_tasks_pending')
    def __init__(self,transport,allowance,started,capacity=4096):
        self.transport=transport;self.allowance=allowance;self.started=started
        self.rows=deque(maxlen=capacity);self.seen=0;self.errors=0;self.closed=False
        self.trends={key:dict(first=None,last=None,maximum=None) for key in self.KEYS}
    def record(self,phase):
        if self.closed:return
        try:
            row=dict(elapsed=round(time.monotonic()-self.started,3),phase=phase if phase in self.PHASES else 'unknown',
                     **resources(),**self.transport.sample())
            self.rows.append(row);self.seen+=1
            for key,trend in self.trends.items():
                value=row.get(key)
                if self.seen==1:trend['first']=value
                trend['last']=value
                if type(value) is int:trend['maximum']=value if trend['maximum'] is None else max(value,trend['maximum'])
        except Exception:
            # Do not interfere with production dict/set mutation or log content.
            # Close future I/O and mark invalid collection instead of fake PASS.
            self.errors+=1;self.allowance.open=False
    def summary(self):return {key:dict(value,maximum_kind='observed_sample_maximum') for key,value in self.trends.items()}

async def run_soak(limits=Limits(),*,providers=None,allow_cloud=False,allow_device=False,stop=None,cloud_budget=None):
    limits.validate()
    if type(allow_cloud) is not bool or type(allow_device) is not bool:raise ProbeLimit('execution_flags')
    if allow_device:raise ProbeLimit('device_driver_not_integrated')
    if providers is not None and not allow_cloud:raise ProbeLimit('cloud_disabled')
    if providers is not None and (providers.dynamic_images is not None or getattr(providers,'probe_cleanup_handle',None) is not None):raise ProbeLimit('provider_not_eligible')
    cloud=providers is not None
    if cloud:
        if type(cloud_budget) is not CloudBudget:raise ProbeLimit('cloud_budget_required')
        cloud_budget.validate()
        limits=replace(limits,allowance_units=min(limits.allowance_units,cloud_budget.max_micro_cny),
                       model_units=cloud_budget.model_request_micro_cny,tts_units=cloud_budget.tts_request_micro_cny)
        limits.validate()
    bundle=providers or UnifiedProviders(OfflineSpeech(),OfflineModel())
    allowance=Allowance(limits);original_model,original_speech=bundle.model,bundle.speech
    usage_before=deepcopy(original_model.metrics()) if hasattr(original_model,'metrics') else {}
    meter=MeterModel(original_model,allowance)
    bundle.model=meter;bundle.speech=MeterSpeech(original_speech,allowance)
    # Retained on unconfirmed cleanup; closed meters must not be bypassed.
    ownership=BatchState();bundle.probe_cleanup_handle=ownership
    transport=BackendTransport(bundle);transport.start()
    started=time.monotonic();deadline=started+limits.duration;stop=stop or asyncio.Event()
    attempts=[];active_seconds=0.;interrupted=False;reason='duration';sampler=None;pending=set();confirmed=False
    collector=ResourceCollector(transport,allowance,started)
    transport.peer.generation_scopes=ObservedScopes(transport.peer.generation_scopes,collector.record)
    transport.peer.retired_tasks=ObservedRetired(transport.peer.retired_tasks,collector.record)
    collector.record('initial')
    async def sample():
        while True:
            collector.record('periodic')
            await asyncio.sleep(limits.sample_interval)
    sampler=asyncio.create_task(sample());ownership.track(sampler)
    async def wait_until(target):
        while not stop.is_set() and time.monotonic()<target:
            await asyncio.sleep(min(.1,target-time.monotonic()))
    try:
        index=0
        while time.monotonic()<deadline and not stop.is_set():
            if index>=limits.max_attempts:reason='attempt_cap';await wait_until(deadline);break
            await wait_until(min(started+index*limits.interval,deadline))
            if stop.is_set() or time.monotonic()>=deadline:break
            label,text,mode=SCENARIOS[index%len(SCENARIOS)]
            row=dict(index=index,scenario=label,injected=mode,started=round(time.monotonic()-started,3),status='failed',observed=None,failure=None)
            attempts.append(row);index+=1;begin=time.monotonic()
            collector.record('attempt_started')
            task=asyncio.create_task(transport.attempt(text,mode));ownership.track(task)
            stopper=asyncio.create_task(stop.wait());ownership.track(stopper)
            done,_=await asyncio.wait({task,stopper},timeout=min(limits.attempt_timeout,max(0,deadline-time.monotonic())),return_when=asyncio.FIRST_COMPLETED)
            stopper.cancel()
            if task not in done:
                row['status']='cancelled' if stop.is_set() else 'timeout'
                row['failure']=failure_metadata(stage=transport.failure_stage,reason=row['status'],transport=transport)
                collector.record('before_attempt_cancel');task.cancel();collector.record('after_attempt_cancel')
                reason=row['status'];break
            try:
                observed=task.result()
                row['observed']=dict(frames=observed['frames'],game_mode=observed['game_mode'],interrupted=observed['interrupted'],
                     first_text_to_transport_ms=None if observed['first_transport_at'] is None else round((observed['first_transport_at']-begin)*1000,2),
                     acoustic_reply_ms=None,interruption_to_speaker_silence_ms=None)
                row['status']='interrupted' if observed['interrupted'] else 'delivered' if observed['delivered'] else 'failed'
                if row['status']=='failed':row['failure']=failure_metadata(stage='delivery',reason='provider',transport=transport)
            except Exception as error:
                row['status']='failed';row['failure']=failure_metadata(error,transport=transport)
            finally:
                active_seconds+=time.monotonic()-begin;row['completed']=round(time.monotonic()-started,3)
                collector.record('attempt_finished')
            if not allowance.open or row['status']=='failed':reason='failure_or_allowance';break
        if stop.is_set():reason='cancelled'
    except asyncio.CancelledError:interrupted=True;reason='caller_cancelled'
    finally:
        for row in attempts:
            if 'completed' not in row:
                row['completed']=round(time.monotonic()-started,3)
                if row['status']=='failed':row['status']='cancelled'
                if row['failure'] is None:row['failure']=failure_metadata(stage=transport.failure_stage,reason='cancelled',transport=transport)
        observation_seconds=time.monotonic()-started
        cleanup_started=time.monotonic()
        collector.record('before_transport_cleanup')
        allowance.open=False
        confirmed,transport_pending=await transport.close();pending|=transport_pending
        collector.record('after_transport_cleanup')
        sampler.cancel()
        for task in ownership.pending():task.cancel()
        if ownership.pending():
            try:await asyncio.wait(ownership.pending(),timeout=.2)
            except asyncio.CancelledError:pass
        pending|=set(ownership.pending());ownership.tasks|=pending
        ownership.open=False;ownership.quarantined=bool(pending) or not confirmed
        collector.record('after_owner_cleanup')
        if not ownership.quarantined:
            bundle.model=original_model;bundle.speech=original_speech;bundle.probe_cleanup_handle=None
    elapsed=time.monotonic()-started
    cleanup_seconds=time.monotonic()-cleanup_started
    active_seconds=sum(max(0,row['completed']-row['started']) for row in attempts)
    collector.record('final');collector.closed=True
    samples=list(collector.rows);trends=collector.summary()
    report=dict(format=1,layer='synthetic_text_real_voicepeer_json_duplex_simulated_ack',cloud_enabled=cloud,device_executed=False,device_events=None,resource_scope='runner_owned_sessions_and_current_process',
                elapsed_seconds=round(elapsed,3),active_attempt_seconds=round(active_seconds,3),effective_interaction_seconds=None,standby_seconds=round(max(0,elapsed-active_seconds-cleanup_seconds),3),cleanup_seconds=round(cleanup_seconds,3),
                requested_seconds=limits.duration,observation_seconds=round(observation_seconds,3),wall_60_minutes_observed=observation_seconds>=3600 and limits.duration==3600,
                limits=asdict(limits),stop_reason=reason,attempted=len(attempts),delivered=sum(r['status']=='delivered' for r in attempts),
                failures=sum(r['status'] in {'failed','timeout','cancelled'} for r in attempts),attempts=attempts,resource_samples=samples,resource_trends=trends,
                sampling=dict(observations=collector.seen,retained=len(samples),evicted=collector.seen-len(samples),errors=collector.errors,
                    active_observed=(trends['active_operations']['maximum'] or 0)>0,continuous_peaks_known=False,
                    valid=collector.errors==0,missing_metrics=[k for k,v in trends.items() if v['maximum'] is None]),
                resource_collection_valid=collector.errors==0 and not ownership.quarantined and bool(attempts) and
                    (trends['active_operations']['maximum'] or 0)>0 and all(v['maximum'] is not None for v in trends.values()) and
                    all(r['status'] in {'delivered','interrupted'} for r in attempts),
                model_stage_calls=meter.stages,model_failed_or_cancelled=meter.failures,usage_delta=usage_delta(usage_before,original_model.metrics() if hasattr(original_model,'metrics') else {}),
                interrupted_attempts=sum(r['status']=='interrupted' for r in attempts),delivery_rate_all_attempts=None if not attempts else sum(r['status']=='delivered' for r in attempts)/len(attempts),
                planned_attempts=limits.max_attempts,not_started=max(0,limits.max_attempts-len(attempts)),
                reservation_unit='operator_reviewed_micro_cny' if cloud else 'synthetic_units',
                billing_bound_verified=False,allowance=allowance.report(),cleanup=dict(confirmed=not ownership.quarantined,pending_tasks=len(pending),provider_reusable=not ownership.quarantined),
                caller_cancelled=interrupted,full_acceptance=False,p14_verified=False,p12_verified=False,p15_verified=False,
                missing=['device_business_driver','real_asr_endpoint','tls_network_observation','acoustic_timings','billing_reconciliation','semantic_review'])
    return report

def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--offline-seconds',type=float,default=3600);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();limits=Limits(duration=args.offline_seconds)
    args.output.write_text(json.dumps(asyncio.run(run_soak(limits)),indent=2)+'\n')

if __name__=='__main__':main()
