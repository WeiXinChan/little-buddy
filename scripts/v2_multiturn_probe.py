"""Synthetic text boundary -> real VoicePeer path. No credential loader/live CLI.

Root supplies an authorized UnifiedProviders instance to run_case; case expectations
are never passed to it. Automatic ACK is transport simulation, never acoustic proof.
"""
import asyncio
from copy import deepcopy
from contextlib import asynccontextmanager
from dataclasses import replace
from hashlib import sha256
import json
import inspect
from types import MappingProxyType
import time
from backend.v2.companion import CompanionPolicy
from backend.v2.voice import VoicePeer as ProductionVoicePeer
from backend.v2.models import TEXT_MODELS

class ProbeLimit(RuntimeError):pass

class BatchState:
    """In-memory cleanup ownership; quarantined instances are never reset/reused."""
    def __init__(self):
        self.open=True;self.tasks=set();self.peer=None;self.quarantined=False
    def ensure(self):
        if not self.open:raise ProbeLimit('batch_closed')
    def track(self,task):
        if task not in self.tasks:
            self.tasks.add(task)
            task.add_done_callback(lambda done:None if done.cancelled() else done.exception())
    def pending(self):
        tasks=self.tasks | (set(self.peer.retired_tasks) if self.peer else set())
        return tuple(task for task in tasks if not task.done())

class ProbeClient:
    """One simulated client command sequence; no direct Session heartbeat calls."""
    def __init__(self,peer,state):
        self.peer=peer;self.state=state;self.epoch=peer.epoch;self.sequence=0
        self.session=peer.session;self.lock=asyncio.Lock();self.heartbeats=0;self.failed=False
    async def send(self,kind,**fields):
        async with self.lock:
            self.state.ensure()
            if self.peer.closed or self.peer.epoch!=self.epoch or self.peer.session is not self.session:
                raise ProbeLimit('client_scope_changed')
            sequence=self.sequence;self.sequence+=1
            await self.peer.handle(json.dumps(dict(v=2,type=kind,epoch=self.epoch,seq=sequence,**fields)))
            if kind=='heartbeat':self.heartbeats+=1

async def client_heartbeat(client):
    # VoiceClient.kt: immediate heartbeat, then handler.postDelayed(...,5000).
    try:
        while client.state.open:
            await client.send('heartbeat')
            await asyncio.sleep(5)
    except Exception:
        client.failed=True;client.state.open=False
        if client.peer.generation:client.peer.generation.cancel()

class ModelMeter:
    def __init__(self,model,state=None):self.inner=model;self.calls=[];self.started=time.monotonic();self.state=state or BatchState()
    async def complete(self,instruction,data,*,schema=None):
        self.state.ensure()
        # Applies before provider I/O, including VoicePeer read retry and summary.
        if len(self.calls)>=24 or time.monotonic()-self.started>=45:raise ProbeLimit('batch_limit')
        encoded=json.dumps(data,ensure_ascii=False).encode()
        if len(encoded)>32768 or len(instruction.encode())>32768:raise ProbeLimit('request_limit')
        stage='plan' if schema and 'mode' in schema.get('properties',{}) else 'facts' if schema and 'facts' in schema.get('properties',{}) else 'safe' if schema and 'allow' in schema.get('properties',{}) else 'compact'
        row={'stage':stage,'ms':None,'ok':False};self.calls.append(row);start=time.monotonic()
        try:
            value=await self.inner.complete(instruction,data,schema=schema);self.state.ensure();row['ok']=True;return value
        finally:row['ms']=round((time.monotonic()-start)*1000,2)

class SpeechMeter:
    def __init__(self,speech,state=None):self.inner=speech;self.calls=0;self.characters=0;self.state=state or BatchState()
    def synthesize(self,text,rate):
        self.state.ensure()
        # Conservative fixed text volume bound; does not claim billing equivalence.
        if self.calls>=12 or self.characters+len(text)>1440:raise ProbeLimit('speech_limit')
        self.calls+=1;self.characters+=len(text)
        return self.inner.synthesize(text,rate)

FAILURE_CODES=frozenset({'voice','timeout','network','quota','safety'})
FAILURE_STAGES=frozenset({'bind','input_policy','plan','facts','fact_commit','safety','synthesis'})
FAILURE_KINDS=frozenset({'WireError','VoiceFault','TimeoutError','ModelError','SafetyFault','ProbeLimit','CancelledError'})

def peer_failure(peer):
    failure=getattr(peer,'last_failure',None)
    if not isinstance(failure,dict):return None
    return {key:failure.get(key) if failure.get(key) in choices else 'unknown'
            for key,choices in (('stage',FAILURE_STAGES),('kind',FAILURE_KINDS))}

class VoicePeer(ProductionVoicePeer):
    """Diagnostic subclass only; delegates all production resource/ACK behavior."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.probe_resources=[]
    @asynccontextmanager
    async def resource(self,manager):
        name=getattr(getattr(manager,'func',None),'__name__',None)
        row={'resource':name if name in {'synthesize','planned'} else 'other',
             'exit_outcome':'not_started','exit_ms':None,'failure_kind':None}
        self.probe_resources.append(row)
        class Tracked:
            async def __aenter__(self):return await manager.__aenter__()
            async def __aexit__(self,*args):
                row['exit_outcome']='started';start=time.monotonic()
                try:
                    value=await manager.__aexit__(*args);row['exit_outcome']='confirmed';return value
                except BaseException as error:
                    row['exit_outcome']='cancelled' if isinstance(error,asyncio.CancelledError) else 'failed'
                    raise
                finally:row['exit_ms']=round((time.monotonic()-start)*1000,2)
        try:
            async with super().resource(Tracked()) as source:yield source
        except BaseException as error:
            row['failure_kind']=type(error).__name__ if type(error).__name__ in FAILURE_KINDS else 'unknown'
            raise

class Sink:
    def __init__(self,ack=True):self.peer=None;self.ack=ack;self.events=[];self.first=None;self.stopped=False;self.frames=0;self.audio_bytes=0;self.max_audio_bytes=0;self.acks=0;self.game_commits=0
    async def send(self,raw):
        if self.stopped:raise ProbeLimit('sink_closed')
        event=json.loads(raw);kind=event['type']
        # Store metadata only. PCM and all response text remain transient.
        row={'type':kind}
        if kind=='failure':row['code']=event.get('code') if event.get('code') in FAILURE_CODES else 'unknown'
        self.events.append(row)
        if kind=='audio':
            size=2*(event['end']-event['start'])
            self.frames+=1;self.audio_bytes+=size;self.max_audio_bytes=max(self.max_audio_bytes,size)
            if self.first is None:self.first=time.monotonic()
            if self.ack:
                p=self.peer;i=replace(p.ack_identity,sequence=p.ack_sequence);p.ack_sequence+=1
                candidate=p.session.pending[0] if p.session.pending else None
                topic=p.session.topic;turn=p.session.turn
                if not p.session.ack(i,player=event['player'],stream=event['stream'],segment=event['segment'],head=event['end']):raise ProbeLimit('ack_rejected')
                # Observe the exact production commit branch, not game presence
                # or value inequality. A same-value state is still a real commit.
                if (candidate is not None and candidate.name==event['segment'] and
                    candidate.state is not None and not candidate.private and
                    event['end']>=candidate.end and p.session.turn==turn and
                    p.session.topic==topic+1 and
                    all(item is not candidate for item in p.session.pending)):
                    self.game_commits+=1
                self.acks+=1;p.changed.set()
    async def close(self,*args):pass

def judge(expect,context,*,previous_heard=(),transport_ok=True):
    """Necessary predicates, not a semantic oracle: wrong/absent terms are flags.

    Context comes only from the actual Session after production playback commit.
    Rule/role semantics (who plays which role, non-repetition correctness, story
    quality) still need root review; these predicates cannot certify those alone.
    """
    game=context.get('game',{});material=game.get('rules','')+' '+json.dumps(game.get('roles',[]),ensure_ascii=False)
    return {'mode':game.get('mode')==expect['mode'],
            'rule_role_terms':all(term in material for term in expect['terms']),
            'played_context':bool(context.get('heard')) and tuple(context['heard'])!=tuple(previous_heard),
            'delivery':transport_ok}

def frozen(value):
    if isinstance(value,dict):return MappingProxyType({key:frozen(item) for key,item in value.items()})
    if isinstance(value,(list,tuple)):return tuple(frozen(item) for item in value)
    return value

def usage_delta(before,after):
    result={}
    for key in ('requests','failures','prompt_tokens','completion_tokens'):
        a=before.get('usage',{}).get(key);b=after.get('usage',{}).get(key)
        missing_before=before.get('usage_missing',{}).get(key)
        missing_after=after.get('usage_missing',{}).get(key)
        known=type(a) is int and type(b) is int and b>=a
        if key.endswith('_tokens'):
            known=known and type(missing_before) is int and type(missing_after) is int and missing_after==missing_before
            # Failed/cancelled requests have no complete provider usage receipt.
            for section,name in (('usage','failures'),(None,'cancelled')):
                old=before.get(section,{}).get(name) if section else before.get(name)
                new=after.get(section,{}).get(name) if section else after.get(name)
                if type(old) is int and type(new) is int and new>old:known=False
        result[key]=b-a if known else None
    return result

async def run_case(case,providers,*,ack=True,observer=None):
    """One explicitly selected 3-turn case. NEVER loops over the whole catalogue.

    Caller owns credentials/network billing authorization and provider cleanup.
    This adapter accepts synthetic input only; ASR/endpoint and actual playback
    are bypassed, while plan/facts/safe/TTS/Session/VoicePeer run unmodified.
    """
    if getattr(providers,'probe_cleanup_handle',None) is not None:raise ProbeLimit('provider_not_reusable')
    if len(case['turns'])!=3:raise ProbeLimit('case_limit')
    if providers.dynamic_images is not None:raise ProbeLimit('images_not_permitted')
    if hasattr(providers.model,'model') and (not isinstance(providers.model.model,str) or providers.model.model not in TEXT_MODELS):raise ProbeLimit('model_mismatch')
    original_model,original_speech=providers.model,providers.speech
    before=deepcopy(original_model.metrics()) if hasattr(original_model,'metrics') else {}
    state=BatchState();providers.probe_cleanup_handle=state
    meter=ModelMeter(original_model,state);speech=SpeechMeter(original_speech,state)
    providers.model=meter;providers.speech=speech
    sink=Sink(ack);peer=VoicePeer(sink,providers,CompanionPolicy());sink.peer=peer
    state.peer=peer
    client=ProbeClient(peer,state)
    heartbeat=asyncio.create_task(client_heartbeat(client));state.track(heartbeat)
    rows=[]
    try:
        async with asyncio.timeout(45):
            for turn in case['turns']:
                previous=peer.session.context().get('heard',())
                peer.session.begin_turn();await peer.commands()
                start=time.monotonic();sink.first=None;sink.events.clear();sink.frames=sink.audio_bytes=sink.max_audio_bytes=sink.acks=sink.game_commits=0;peer.probe_resources.clear();offset=len(meter.calls)
                peer.generation=asyncio.create_task(peer.respond(turn['input'],peer.epoch))
                await client.send('bind',player='probe-'+str(peer.session.turn))
                try:await asyncio.shield(peer.generation)
                except asyncio.CancelledError:
                    if client.failed:raise ProbeLimit('client_heartbeat_failed') from None
                    raise
                if client.failed:raise ProbeLimit('client_heartbeat_failed')
                context=peer.session.context()
                ok=any(e['type']=='reply_end' for e in sink.events) and not any(e['type']=='failure' for e in sink.events)
                checks=judge(turn['expect'],context,previous_heard=previous,transport_ok=ok)
                if observer is not None:
                    # Detached immutable snapshot only: no Session/provider/PCM/expect.
                    observation=frozen(deepcopy(context))
                    result=observer(turn['label'],observation)
                    if inspect.isawaitable(result):
                        if inspect.iscoroutine(result):result.close()
                        else:
                            rejected=asyncio.ensure_future(result);state.track(rejected);rejected.cancel()
                        raise ProbeLimit('observer_must_be_sync')
                rows.append(dict(label=turn['label'],checks=checks,quality_assessable=ok,
                    peer_failure=peer_failure(peer),resource_diagnostics=deepcopy(peer.probe_resources),control_failures=[e['code'] for e in sink.events if e['type']=='failure'],
                    delivery_metadata=dict(audio_chunks=sink.frames,audio_bytes=sink.audio_bytes,max_audio_bytes=sink.max_audio_bytes,acks_accepted=sink.acks,game_committed=sink.game_commits>0,resource_quarantined=peer.quarantined),
                    first_audio_after_text_ms=None if sink.first is None else round((sink.first-start)*1000,2),
                    completed_ms=round((time.monotonic()-start)*1000,2),stages=deepcopy(meter.calls[offset:])))
                if not all(checks.values()):break # stop the batch; no quality retry
    except Exception as error:
        rows.append({'label':'batch-stop','failure':type(error).__name__}) # no messages/provider payload
    finally:
        # Revoke before cleanup, including meter/sink: no late task may issue a
        # new unmetered request or publish after the batch has returned.
        state.open=False;sink.stopped=True;peer.closed=True
        peer.invalidate_visual();peer.session.clear()
        if peer.generation:state.track(peer.generation)
        cleanup_deadline=asyncio.get_running_loop().time()+.2
        while True:
            for task in peer.retired_tasks:state.track(task)
            pending=state.pending()
            for task in pending:task.cancel()
            remaining=cleanup_deadline-asyncio.get_running_loop().time()
            if not pending or remaining<=0:break
            try:
                # asyncio.wait observes a deadline without waiting for cancel
                # acknowledgement from tasks that may swallow cancellation.
                await asyncio.wait(pending,timeout=remaining)
            except asyncio.CancelledError:
                break # repeated caller cancellation never grants more cleanup time
        for task in state.tasks:
            if task.done() and not task.cancelled():task.exception()
        state.quarantined=bool(state.pending()) or peer.quarantined
        if state.quarantined:
            rows.append({'label':'batch-stop','failure':'ProviderQuarantined'})
            # Keep closed meters + handle attached; never silently restore raw
            # provider access while exit/lifetime cannot be confirmed.
        else:
            providers.model=original_model;providers.speech=original_speech
            providers.probe_cleanup_handle=None
    metrics=original_model.metrics() if hasattr(original_model,'metrics') else {}
    usage=usage_delta(before,metrics)
    return dict(format=1,client_heartbeats=client.heartbeats,client_heartbeat_failed=client.failed,peer_failure=peer_failure(peer),cleanup={'confirmed':not state.quarantined,'pending_tasks':len(state.pending()),'provider_reusable':not state.quarantined},usage_final=not state.quarantined,usage=usage,case=case['id'],fixture_sha256=sha256(json.dumps(case,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
                layer='synthetic_text_real_voicepeer_simulated_playback',turns=rows,model_requests=len(meter.calls),
                tts_requests=speech.calls,tts_unicode_characters=speech.characters,
                full_acceptance=False,semantic_review_required=True,p12_verified=False,p15_verified=False)

def main():
    import argparse
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list',action='store_true',required=True,help='offline fixture inventory only; cannot initiate cloud')
    parser.parse_args()
    fixture=Path(__file__).resolve().parents[1]/'docs/testing/v2/multiturn/cases.json'
    data=json.loads(fixture.read_text())
    print(json.dumps({'format':1,'sha256':sha256(fixture.read_bytes()).hexdigest(),
        'cases':[{'id':c['id'],'turns':len(c['turns'])} for c in data['cases']],
        'cloud_calls':0},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
