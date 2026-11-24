import asyncio,base64,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'little-buddy'))
from backend.v2.voice import VoicePeer
from backend.v2.fixture import SyntheticProviders,SyntheticPolicy
class Socket:
 def __init__(self): self.sent=[]
 async def send(self,raw): self.sent.append(json.loads(raw))
async def main():
 now=[0.0]; sock=Socket(); providers=SyntheticProviders(); peer=VoicePeer(sock,providers,SyntheticPolicy(),clock=lambda:now[0]); seq=0
 async def event(kind,**fields):
  nonlocal seq
  await peer.handle(json.dumps(dict(v=2,type=kind,epoch=peer.epoch,seq=seq,**fields))); seq+=1
 # Actual input revision/probe path. Fake only the monotonic clock, not production decisions.
 await event('advance',revision=1)
 await event('input',pcm=base64.b64encode(b'\x01\x00'*320).decode())
 async def delayed_endpoint(text,context):
  now[0]=14.0
  return dict(completion='complete',meaning='new_turn')
 providers.endpoint=delayed_endpoint
 await event('probe',revision=1); await peer.recognition
 await event('seal',revision=1)
 intent=sock.sent[-1]['intent']
 await peer.handle(json.dumps(dict(v=2,type='stop',epoch=1,seq=0,intent=intent))); seq=1
 deadline=peer.session.deadline
 # Heartbeat is sent before its separate 15s connection lease expires.
 now[0]=14.5; await event('heartbeat')
 now[0]=16.0; peer.session.poll()
 out=dict(case='R97-01',input_at=0,analysis_done_at=14,deadline=deadline,at=16,
          response_confirmed=peer.session.response_confirmed,response_expired=peer.session.response_expired,
          output_still_live=peer.session._output_live(),expected_deadline_upper_bound=15,
          defect_reproduced=deadline>15 and not peer.session.response_expired)
 print(json.dumps(out,indent=2));
 if peer.generation: peer.generation.cancel(); await asyncio.gather(peer.generation,return_exceptions=True)
 assert out['defect_reproduced'],'known-bad negative control no longer reproduces; review result needs update'
asyncio.run(main())
