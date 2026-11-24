"""Independent deterministic review. Run with PYTHONPATH=little-buddy python3 probe99.py."""
import asyncio, json, sys, inspect, textwrap
from contextlib import asynccontextmanager
from dataclasses import replace
from backend.v2.voice import VoicePeer
from backend.v2.companion import CompanionPolicy

class Socket:
    def __init__(self): self.events=[]; self.peer=None
    async def send(self, raw):
        event=json.loads(raw); self.events.append(event)
        if event['type']=='audio':
            p=self.peer
            assert p.session.ack(replace(p.ack_identity,sequence=p.ack_sequence),player=event['player'],stream=event['stream'],segment=event['segment'],head=event['end'])
            p.ack_sequence+=1; p.changed.set()
    async def close(self,*args): pass

class Providers:
    def __init__(self):
        self.entered=asyncio.Event(); self.release=asyncio.Event(); self.cancelled=False
        self.calls=[]; self.action='continue'
    @asynccontextmanager
    async def recognize(self,rate): yield self
    async def write(self,pcm): pass
    async def finish(self):
        self.entered.set()
        try: await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled=True
            await self.release.wait()  # legitimate adversarial supplier ignores cancellation
        return '旧参与者合成私事'
    async def endpoint(self,text,context):
        self.calls.append((text,context))
        return dict(completion='complete',meaning='new_turn')
    async def plan(self,text,context):
        return dict(action=self.action,mode='chat',rules='',roles=[],secrets={},sentences=['合成回应'],anchors={})
    async def facts(self,text):
        return [dict(key='preference',start=0,end=len(text),value=text)] if text.startswith('我喜欢') else []
    async def safe(self,*args): return True
    @asynccontextmanager
    async def synthesize(self,*args):
        async def chunks(): yield b'\1\0'*100
        yield chunks()

async def turn(p,text):
    p.session.begin_turn(); p.session.drain_commands()
    p.generation=asyncio.create_task(p.respond(text,p.epoch))
    await p.handle(json.dumps(dict(v=2,type='bind',epoch=p.epoch,seq=p.sequence+1,player='synthetic')))
    await asyncio.wait_for(p.generation,2)

async def main():
    out={}
    if '--negative-control' in sys.argv:
        # Deliberately wrong in-memory method, never alters reviewed source.
        original=VoicePeer.analyze
        source=textwrap.dedent(inspect.getsource(original)).replace(' or session_id != self.session.session','')
        namespace={};exec(source,original.__globals__,namespace)
        VoicePeer.analyze=namespace['analyze']
        out['negative_control']='session identity guard removed in memory'
    # Actual handoff branch, old ASR has already started before cancellation.
    pr=Providers(); sock=Socket(); p=VoicePeer(sock,pr,CompanionPolicy()); sock.peer=p
    await turn(p,'我喜欢猫')
    p.input_budget.speech(0)
    p.recognition=asyncio.create_task(p.analyze(b'\1\0',p.epoch,p.revision))
    await pr.entered.wait()
    old=p.session; pr.action='handoff'
    await turn(p,'换另一个人单独玩')
    assert p.session is not old and not old.active
    p.session.private_mode=True
    p.session.record_input('新参与者合成私事',[])
    pr.release.set(); await asyncio.wait_for(p.recognition,2)
    out['handoff_cancel_swallowed']=pr.cancelled
    out['stale_analysis_rejected']=p.analysis is None
    out['stale_asr_dispatched_with_new_context']=bool(pr.calls and '新参与者合成私事' in str(pr.calls[-1][1]))
    # Production VoicePeer, distinct still-current dimensions, far below capacity.
    pr=Providers(); sock=Socket(); p=VoicePeer(sock,pr,CompanionPolicy()); sock.peer=p
    for n,text in enumerate(['我喜欢猫','我喜欢蓝色','我喜欢面条','我喜欢足球','我喜欢下棋']):
        await turn(p,text)
        if n==3: out['four_dimensions_cat_present']='我喜欢猫' in str(p.session.context()['facts'])
    for n in range(10): await turn(p,f'合成背景{n}')
    context=p.session.context()
    out['unretracted_animal_preference_survives']= '我喜欢猫' in str(context)
    out['memory_bytes']=len(json.dumps(dict(public=p.session.public,private=p.session.private,game=p.session.game,secrets=p.session.secrets,recent=p.session.recent,facts=p.session.facts,pending=[]),ensure_ascii=False).encode())
    out['no_product_failure']=not any(e['type']=='failure' for e in sock.events)
    # Endpoint already running when actual handoff cancels it; it too ignores
    # cancellation. Guard must reject its completion at unchanged epoch/revision.
    pr=Providers();sock=Socket();p=VoicePeer(sock,pr,CompanionPolicy());sock.peer=p
    await turn(p,'我喜欢猫');pr.release.set();started=asyncio.Event();release=asyncio.Event()
    async def endpoint(text,context):
        started.set()
        try: await release.wait()
        except asyncio.CancelledError: await release.wait()
        return dict(completion='complete',meaning='new_turn')
    pr.endpoint=endpoint;p.input_budget.speech(0)
    p.recognition=asyncio.create_task(p.analyze(b'\1\0',p.epoch,p.revision));await started.wait()
    pr.action='handoff';await turn(p,'换另一个人单独玩')
    release.set();await asyncio.wait_for(p.recognition,2)
    out['late_endpoint_analysis_rejected']=p.analysis is None
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__': asyncio.run(main())
