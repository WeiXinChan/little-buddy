"""Independent assertions; engineering evidence, never acoustic acceptance."""
import asyncio,json,copy
from dataclasses import replace
from backend.v2.session import Session
from backend.v2.voice import VoicePeer
from backend.v2.companion import CompanionPolicy
from probe99 import Socket,Providers,turn

async def main():
    checks={}
    def check(name,result): checks[name]=bool(result)
    s=Session(lambda:0);s.begin_turn();s.drain_commands();stream=s.bind_player('old')
    tx=s.task('tts');ack=s.task('ack');s.drain_commands()
    check('valid_send',s.send(tx,name='one',public='已播关键线索',end=100,approved=True,anchors=('clue.current',)))
    for field,value in [('connection',99),('session','wrong'),('turn',99),('output',99),('task','wrong'),('sequence',99)]:
        before=copy.deepcopy((s.public,s.pending,s.facts,s.tasks))
        check('bad_ack_'+field,not s.ack(replace(ack,**{field:value}),player='old',stream=stream,segment='one',head=100) and before==(s.public,s.pending,s.facts,s.tasks))
    check('valid_ack',s.ack(ack,player='old',stream=stream,segment='one',head=100))
    snap=s.memory_snapshot();s.interrupt()
    check('old_summary_rejected',not s.compact(snap,[]))
    s.handoff();fresh=Session(lambda:0);fresh.begin_turn();fresh.drain_commands()
    check('old_image_rejected',not fresh.image_ready(tx,topic=fresh.topic))
    check('old_session_all_empty',not any((s.public,s.private,s.facts,s.recent,s.game,s.secrets,s.pending,s.tasks)))
    before=copy.deepcopy((fresh.recent,fresh.facts,fresh.memory_revision))
    fresh.content_limit=200
    try: fresh.record_input('我喜欢猫'*100,[dict(key='preference',start=0,end=4,value='我喜欢猫')])
    except BufferError: pass
    check('capacity_atomic',before==(fresh.recent,fresh.facts,fresh.memory_revision))
    pr=Providers();sock=Socket();p=VoicePeer(sock,pr,CompanionPolicy());sock.peer=p
    await turn(p,'我喜欢猫');sid=p.session.session
    pr.action='change';await turn(p,'交换角色')
    check('role_change_preserves_session',p.session.session==sid and '我喜欢猫' in str(p.session.context()))
    pr.action='continue';total=0
    async def compact(facts): return []
    pr.compact=compact
    async def long_plan(text,context):
        return dict(action='continue',mode='story',rules='',roles=[],secrets={},
            sentences=['已播星球故事背景，'*20],anchors={'clue.current':0})
    pr.plan=long_plan
    for n in range(140):
        text=f'第{n}轮背景，'+'星球故事'*70; total+=len(text.encode())
        await turn(p,text)
    check('long_production_140_turns',total>65536 and p.session._fits() and len([e for e in sock.events if e['type']=='audio'])>128)
    check('long_protected_child_source','我喜欢猫' in str(p.session.context()))
    check('long_no_failures',not any(e['type']=='failure' for e in sock.events))
    print(json.dumps(dict(checks=checks,passed=sum(checks.values()),total=len(checks),cumulative_input_bytes=total,cumulative_output_bytes=sum(len('已播星球故事背景，'.encode())*20 for _ in range(140)),failure=getattr(p,'last_failure',None),audio=sum(e['type']=='audio' for e in sock.events),retained=len(p.session.public)),ensure_ascii=False,indent=2))

if __name__=='__main__':asyncio.run(main())
