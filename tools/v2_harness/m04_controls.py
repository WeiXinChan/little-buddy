"""Literal oracle against production core + deliberate wrong implementations.
No adapter self-report. All text/audio here is synthetic. Exit nonzero if the
production code fails or any negative control escapes detection.
"""
import json
from dataclasses import replace
from pathlib import Path
from backend.v2.session import Session


def run(cls):
    t=[0]; s=cls(lambda:t[0]); s.begin_turn(); stream=s.bind_player('p')
    tx, ack=s.task('tts'),s.task('ack'); s.drain_commands()
    assert s.send(tx,name='first',public='heard',end=100,approved=True)
    assert s.ack(ack,player='p',stream=stream,segment='first',head=100)
    assert s.send(replace(tx,sequence=1),name='second',public='unheard',end=200,approved=True)
    for n in range(10,60,10): t[0]=n; s.heartbeat()
    s.ack(replace(ack,sequence=1),player='p',stream=stream,segment='second',head=100)
    t[0]=60; s.heartbeat(); s.poll()
    return (s.player is None and s.response_expired and s.context()['heard']==('heard',)
            and any(c[0]=='mute_flush' for c in s.drain_commands()))


def main():
    source=Path('backend/v2/session.py').read_text()
    controls={
        'same_head_refreshes_deadline': source.replace('if self.response_confirmed and advanced:', 'if self.response_confirmed:'),
        'ignores_output_deadline': source.replace('if not limit or self.clock() >= limit:', 'if not limit:'),
        'fake_ack_confirms_full_segment': source.replace('        self.head = head', '        head = self.sent_end\n        self.head = head'),
    }
    rows=[dict(case='production_stall_releases',passed=run(Session))]
    for name, broken in controls.items():
        namespace={'__name__':'backend.v2.session'}
        exec(compile(broken,name,'exec'),namespace)
        detected=not run(namespace['Session'])
        rows.append(dict(case=name,negative_control_detected=detected,passed=detected))
    print(json.dumps(dict(scope='synthetic module oracle; not non-author review',checks=rows),indent=2))
    if not all(r['passed'] for r in rows): raise SystemExit(1)


if __name__=='__main__': main()
