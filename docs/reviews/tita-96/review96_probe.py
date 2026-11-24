import json, sys
from dataclasses import replace
sys.path.insert(0, 'little-buddy')
from backend.v2.session import Session
from tools.v2_harness.session_adapter import SessionAdapter, assert_stop

results = []
def record(name, expected, actual):
    results.append(dict(case=name, expected=expected, actual=actual, passed=expected == actual))
def fresh():
    clock = [0]
    s = Session(lambda: clock[0])
    s.begin_turn(); stream = s.bind_player('p'); s.drain_commands()
    return clock, s, stream, s.task('tts'), s.task('ack')

for reason in ('flush','stop','rebuild','wrap','route-loss'):
    c,s,stream,e,a = fresh()
    assert s.send(e,name='a',public='clue',answer='answer',end=100,effect='image',approved=True)
    s.reset_player(reason); s.drain_commands()
    record(reason, [False, [], False, False], [s.ack(a,player='p',stream=stream,segment='a',head=100),list(s.context()['heard']),s.image_ready(e,topic=s.topic),s.send(e,name='late',public='late',end=200,approved=True)])

c,s,stream,e,a = fresh()
assert s.send(e,name='story',public='valid response',end=100,approved=True)
assert s.ack(a,player='p',stream=stream,segment='story',head=100)
c[0]=10; s.heartbeat(); c[0]=15
record('response_received_before_budget_later_story_chunk', True,
       s.send(replace(e,sequence=1),name='continued',public='next story sentence',end=200,approved=True))

c,s,stream,e,a = fresh()
for i in range(127):
    assert s.send(replace(e,sequence=i),name=str(i),public='x',end=i+1,approved=True)
    assert s.ack(replace(a,sequence=i),player='p',stream=stream,segment=str(i),head=i+1)
    s.drain_commands()
assert s.send(replace(e,sequence=127),name='127',public='x',end=128,approved=True)
assert s.send(replace(e,sequence=128),name='128',public='x',end=129,approved=True)
assert s.ack(replace(a,sequence=127),player='p',stream=stream,segment='127',head=128)
assert s.ack(replace(a,sequence=128),player='p',stream=stream,segment='128',head=129)
record('revealed_capacity_reserves_pending',128,len(s.revealed))

c,s,stream,e,a = fresh()
before=(s.output,s.topic,s.game.copy())
try: s.change_game(rules='new',roles=[],secrets=['invalid'])
except (ValueError,TypeError): pass
record('invalid_game_atomic', list(before),[s.output,s.topic,s.game])

c,s,stream,e,a = fresh()
s.remember_private('synthetic private')
s.change_game(rules='rule',roles=['child','robot'],secrets={'answer':'hidden'})
record('shared_privacy', [[],{}], [list(s.context(shared=True)['private']),s.context(shared=True)['unrevealed']])
s.handoff()
record('handoff_cleanup', [{},0,0], [s.context(),len(s.pending),len(s.tasks)])
c,s,stream,e,a = fresh()
deadline=s.deadline
c[0]=10; s.heartbeat(); retried=s.retry(safe=True,idempotent=True)
record('retry_budget_unchanged', [True,15,False], [retried,s.deadline,s.retry(safe=True,idempotent=True)])
c,s,stream,e,a = fresh()
for t in range(5,1201,5):
    c[0]=t; assert s.heartbeat()
    if t % 100 == 0: assert s.valid_interaction()
record('long_active_conversation', [True,1800], [s.active,s.expires])
for t in range(1205,1800,5): c[0]=t; assert s.heartbeat()
c[0]=1800
record('idle_ttl_cleanup',False,s.poll())
c,s,stream,e,a = fresh()
s.remember_private('p'*40000)
record('combined_capacity_reject',False,s.send(e,name='huge',public='q'*30000,end=100,approved=True))

for empty in (None,{}, {'old_ack':True,'heard':(),'reveals':0}):
    try: assert_stop(empty); rejected=False
    except AssertionError: rejected=True
    record('empty_or_wrong_adapter',True,rejected)
class Broken(Session):
    def ack(self,*args,**kwargs): return True
try: assert_stop(SessionAdapter(Broken).stop_case()); rejected=False
except AssertionError: rejected=True
record('broken_implementation',True,rejected)
print(json.dumps(results,ensure_ascii=False,indent=2))
