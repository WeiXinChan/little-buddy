"""Synthetic text boundary -> real VoicePeer path. No credential loader/live CLI.

Root supplies an authorized UnifiedProviders instance to run_case; case expectations
are never passed to it. Automatic ACK is transport simulation, never acoustic proof.
"""
import asyncio
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
import time
from backend.v2.companion import CompanionPolicy
from backend.v2.voice import VoicePeer
from backend.v2.models import TEXT_MODEL

class ProbeLimit(RuntimeError):pass

class ModelMeter:
    def __init__(self,model):self.inner=model;self.calls=[];self.started=time.monotonic()
    async def complete(self,instruction,data,*,schema=None):
        # Applies before provider I/O, including VoicePeer read retry and summary.
        if len(self.calls)>=24 or time.monotonic()-self.started>=45:raise ProbeLimit('batch_limit')
        encoded=json.dumps(data,ensure_ascii=False).encode()
        if len(encoded)>32768 or len(instruction.encode())>32768:raise ProbeLimit('request_limit')
        stage='plan' if schema and 'mode' in schema.get('properties',{}) else 'facts' if schema and 'facts' in schema.get('properties',{}) else 'safe' if schema and 'allow' in schema.get('properties',{}) else 'compact'
        row={'stage':stage,'ms':None,'ok':False};self.calls.append(row);start=time.monotonic()
        try:
            value=await self.inner.complete(instruction,data,schema=schema);row['ok']=True;return value
        finally:row['ms']=round((time.monotonic()-start)*1000,2)

class SpeechMeter:
    def __init__(self,speech):self.inner=speech;self.calls=0;self.characters=0
    def synthesize(self,text,rate):
        # Conservative fixed text volume bound; does not claim billing equivalence.
        if self.calls>=12 or self.characters+len(text)>1440:raise ProbeLimit('speech_limit')
        self.calls+=1;self.characters+=len(text)
        return self.inner.synthesize(text,rate)

class Sink:
    def __init__(self,ack=True):self.peer=None;self.ack=ack;self.events=[];self.first=None
    async def send(self,raw):
        event=json.loads(raw);kind=event['type']
        # Store metadata only. PCM and all response text remain transient.
        self.events.append({'type':kind})
        if kind=='audio':
            if self.first is None:self.first=time.monotonic()
            if self.ack:
                p=self.peer;i=replace(p.ack_identity,sequence=p.ack_sequence);p.ack_sequence+=1
                if not p.session.ack(i,player=event['player'],stream=event['stream'],segment=event['segment'],head=event['end']):raise ProbeLimit('ack_rejected')
                p.changed.set()
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

async def run_case(case,providers,*,ack=True):
    """One explicitly selected 3-turn case. NEVER loops over the whole catalogue.

    Caller owns credentials/network billing authorization and provider cleanup.
    This adapter accepts synthetic input only; ASR/endpoint and actual playback
    are bypassed, while plan/facts/safe/TTS/Session/VoicePeer run unmodified.
    """
    if len(case['turns'])!=3:raise ProbeLimit('case_limit')
    if providers.dynamic_images is not None:raise ProbeLimit('images_not_permitted')
    if hasattr(providers.model,'model') and providers.model.model!=TEXT_MODEL:raise ProbeLimit('model_mismatch')
    original_model,original_speech=providers.model,providers.speech
    meter=ModelMeter(original_model);speech=SpeechMeter(original_speech)
    providers.model=meter;providers.speech=speech
    sink=Sink(ack);peer=VoicePeer(sink,providers,CompanionPolicy());sink.peer=peer
    rows=[]
    try:
        async with asyncio.timeout(45):
            for turn in case['turns']:
                previous=peer.session.context().get('heard',())
                peer.session.begin_turn();await peer.commands()
                start=time.monotonic();sink.first=None;sink.events.clear();offset=len(meter.calls)
                peer.generation=asyncio.create_task(peer.respond(turn['input'],peer.epoch))
                await peer.handle(json.dumps(dict(v=2,type='bind',epoch=peer.epoch,seq=peer.sequence+1,player='probe-'+str(peer.session.turn))))
                await peer.generation
                context=peer.session.context()
                ok=any(e['type']=='reply_end' for e in sink.events) and not any(e['type']=='failure' for e in sink.events)
                checks=judge(turn['expect'],context,previous_heard=previous,transport_ok=ok)
                rows.append(dict(label=turn['label'],checks=checks,
                    first_audio_after_text_ms=None if sink.first is None else round((sink.first-start)*1000,2),
                    completed_ms=round((time.monotonic()-start)*1000,2),stages=deepcopy(meter.calls[offset:])))
                if not all(checks.values()):break # stop the batch; no quality retry
    except Exception as error:
        rows.append({'label':'batch-stop','failure':type(error).__name__}) # no messages/provider payload
    finally:
        if peer.generation and not peer.generation.done():peer.generation.cancel()
        await asyncio.gather(*([peer.generation] if peer.generation else []),*peer.retired_tasks,return_exceptions=True)
        peer.invalidate_visual();peer.session.clear()
        providers.model=original_model;providers.speech=original_speech
    metrics=original_model.metrics() if hasattr(original_model,'metrics') else {}
    usage={key:metrics.get('usage',{}).get(key) for key in ('requests','failures','prompt_tokens','completion_tokens')}
    return dict(format=1,usage=usage,case=case['id'],fixture_sha256=sha256(json.dumps(case,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
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
