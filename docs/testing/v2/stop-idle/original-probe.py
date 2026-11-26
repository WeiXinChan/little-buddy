import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,'/home/ubuntu/tech/v2-delivery/soak-source-7f3bd941')
from scripts.v2_soak import BackendTransport,OfflineModel,OfflineSpeech
from backend.v2.companion import UnifiedProviders
async def main():
 t=BackendTransport(UnifiedProviders(OfflineSpeech(),OfflineModel()));p=t.peer;now=[100.]
 p.session.clock=lambda:now[0];p.session.expires=1000.;p.session.heartbeat_deadline=1000.
 p.session.begin_turn();await p.commands();before=p.session.deadline
 await p.handle(json.dumps(dict(v=2,type='stop',epoch=1,seq=0,intent='synthetic-stop')))
 after=p.session.deadline;now[0]=before+.01
 await asyncio.wait_for(p.monitor(),1)
 events=[]
 while not t.socket.outgoing.empty():events.append(json.loads(t.socket.outgoing.get_nowait()))
 report=dict(source='7f3bd941d4af8a7c283f68ceda16fa41bfff532d',controlled_clock=True,cloud_calls=0,device=False,deadline_before_stop=before,deadline_after_stop=after,clock_after_original_deadline=now[0],response_expired=p.session.response_expired,timeout_sent=any(e.get('type')=='failure' and e.get('code')=='timeout' for e in events),scope='actual stop handler and monitor; no active TTS/resource; production run exits when monitor returns')
 await t.close();Path('/home/ubuntu/tech/v2-delivery/stop-idle-deadline-counterexample.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
asyncio.run(main())
