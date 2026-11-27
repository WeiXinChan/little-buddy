"""Offline synthetic cold-source preparation; never opens a provider or network."""
import hashlib
from backend.v2.memory import unpack
from backend.v2.session import Session

QUERY='我很早说过不喜欢哪种饼干、喜欢哪种？'
SOURCE='我不喜欢薄荷味饼干，我喜欢南瓜饼干。'

def prepare():
    s=Session(__import__('time').monotonic)
    for n in range(70):
        text=SOURCE if n==0 else f'我喜欢第{n}种云朵图案'
        s.record_input(text,[dict(key='preference',value=text,start=0,end=len(text))])
        s.begin_turn();s.drain_commands();s.bind_player('synthetic');s.drain_commands()
        name=f'background-{n}'
        if not s.send(s.task('tts'),name=name,public=f'合成背景第{n}段。',end=240,approved=True):raise ValueError('setup_send')
        if not s.ack(s.task('ack'),player='synthetic',stream=s.stream,segment=name,head=240):raise ValueError('setup_ack')
    cold=unpack(s.source_archive)
    matches=[v for _,v in cold.values() if v['source_text']==SOURCE]
    if len(matches)!=1:raise ValueError('source_not_cold')
    source_id=matches[0]['source_id']
    if any(v.get('source_id')==source_id for v in s.facts.values()):raise ValueError('source_still_hot')
    before=s.context(query='背景');snapshot=s.memory_snapshot()
    if SOURCE in str(before['recent']) or SOURCE in str(before['heard']):raise ValueError('source_still_recent')
    if not s.compact(snapshot,[]):raise ValueError('compact_not_applied')
    context=s.context(query=QUERY)
    if not any(v.get('source_id')==source_id and v['source_text']==SOURCE for v in context['facts'].values()):raise ValueError('cold_not_retrieved')
    return s,dict(synthetic_only=True,cloud_calls=0,source_id=source_id,source_sha256=hashlib.sha256(SOURCE.encode()).hexdigest(),
        archive_sources=len(cold),not_hot=True,not_recent=True,compact_returned=True,
        before_heard=len(before['heard']),after_heard=len(context['heard']),query=QUERY,
        retrieved_exact_source=True,reviewed=False,played=False,semantic_pass=None)

if __name__=='__main__':
    import json
    _,evidence=prepare();print(json.dumps(evidence,ensure_ascii=False))
