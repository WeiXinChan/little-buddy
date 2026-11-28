"""Loopback event-loop playout clock, real VoicePeer audio frames and identity-checked ACKs."""
import asyncio,json,unittest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from contextlib import asynccontextmanager
from backend.v2.companion import CompanionPolicy,UnifiedProviders
from backend.v2.voice import VoicePeer
from tests.v2.test_m05 import Model,plan


async def measure(wide,interrupt=False):
    loop=asyncio.get_running_loop(); now=loop.time
    produces=[];reviews=[];opens=[];ends=[];sent=[];transmitted=[];samples=[];jobs=[];peak=0;full=asyncio.Event();waits=[]
    class Provider:
        @asynccontextmanager
        async def synthesize(self,text,rate):
            opens.append(now())
            async def frames():
                await asyncio.sleep(.012)
                for _ in range(24):
                    await asyncio.sleep(.003)
                    produces.append(now());yield bytes(960) # 20 ms at 24 kHz
            yield frames()
            ends.append(now())
    class Reviewer(Model):
        async def complete(self,instruction,data,**kwargs):
            if '审核下一个' in instruction:
                start=now();await asyncio.sleep(.008);reviews.append((start,now()))
            return await super().complete(instruction,data,**kwargs)
    class Wire:
        async def receive(self,raw):
            nonlocal peak
            e=json.loads(raw)
            if e['type']=='bound':self.identity=e['identity']
            if e['type']!='audio':return
            t=now();sent.append(t);peak=max(peak,len(p.session.pending))
            prev=self.tail if samples else t
            self.loss=getattr(self,'loss',0)+round(max(0,t-prev)*24000)
            self.tail=max(t,prev)+(e['end']-e['start'])/24000
            samples.append((e['end'],self.loss))
            async def ack(played,seq):
                # Send ACK only after the simulated native head reached end,
                # then deliver over a fixed 35 ms return path.
                await asyncio.sleep(max(0,played+.035-now()))
                await client.send(json.dumps(dict(v=2,type='ack',epoch=0,seq=seq+1,
                    identity=dict(self.identity,sequence=seq),player='p',stream=e['stream'],
                    segment=e['segment'],head=e['end'])))
            if interrupt:
                if len(sent)==4:full.set()
                return
            jobs.append(asyncio.create_task(ack(self.tail,len(samples)-1)))
    class TimedPeer(VoicePeer):
        async def send(self,kind,**fields):
            await super().send(kind,**fields)
            if kind=='audio':transmitted.append(now())

        async def audio(self,*args,**kw):
            start=now();blocked=len(self.session.pending)>=self.session.audio_capacity
            await super().audio(*args,**kw)
            if blocked:waits.append(now()-start)
    wire=Wire()
    model=Reviewer(plan(anchors={},tools=[]))
    model.next_plan['sentences']=['一起看云吧。','云像一只小羊。']
    ready=asyncio.Event();done=asyncio.Event();p=None
    async def server(ws):
        nonlocal p
        p=TimedPeer(ws,UnifiedProviders(Provider(),model),CompanionPolicy(),wide_audio_window=wide)
        p.session.begin_turn();p.session.drain_commands()
        p.generation=asyncio.create_task(p.respond('讲两句故事',0))
        ready.set()
        async for raw in ws:
            await p.handle(raw)
            if interrupt and p.generation is None:done.set()
    async with serve(server,'127.0.0.1',0) as listener:
        port=listener.sockets[0].getsockname()[1]
        async with connect(f'ws://127.0.0.1:{port}',proxy=None) as client:
            await ready.wait()
            await client.send(json.dumps(dict(v=2,type='bind',epoch=0,seq=0,player='p')))
            async with asyncio.timeout(5):
                while True:
                    raw=await client.recv()
                    if json.loads(raw)['type']=='reply_end':break
                    await wire.receive(raw)
                    if interrupt and full.is_set():
                        assert not p.session.response_confirmed and p.session.head==0
                        await client.send(json.dumps(dict(v=2,type='stop',epoch=1,seq=0,intent='')))
                        await done.wait()
                        assert not p.session.pending and not p.session.public and not p.session.game
                        assert p.generation is None and len(sent)==4 and not p.quarantined
                        return
            await asyncio.gather(*jobs)
    assert list(p.session.public)==model.next_plan['sentences'] and p.session.head==48*480
    return dict(peak=peak,blocked_ms=round(sum(waits)*1000),strict_loss=sum(b[1]-a[1] for a,b in zip(samples,samples[1:]) if 0<a[0]<b[0]<samples[-1][0]),
        max_send_gap_ms=round(max(b-a for a,b in zip(transmitted,transmitted[1:]))*1000),
        max_pull_gap_ms=round(max(produces[i]-produces[i-1] for i in range(1,48) if i!=24)*1000),
        provider_delay_ms=3,review_ms=round((reviews[-1][1]-reviews[-1][0])*1000),
        between_resources_ms=round((opens[1]-ends[0])*1000),second_open_to_pcm_ms=round((produces[24]-opens[1])*1000))

class Supply(unittest.IsolatedAsyncioTestCase):
    async def test_stop_with_four_unplayed_packets(self):
        await measure(True,interrupt=True)

    async def test_delayed_played_ack(self):
        narrow=await measure(False);wide=await measure(True)
        print('synthetic_stream',narrow,wide)
        self.assertEqual(narrow['peak'],2);self.assertEqual(wide['peak'],4)
        self.assertLess(wide['strict_loss'],narrow['strict_loss']*.5)
