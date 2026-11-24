"""Synthetic transport driving the actual production core, not lab doubles."""
from dataclasses import replace
from backend.v2.session import Session
from tools.v2_harness.lab import Clock


class SessionAdapter:
    def __init__(self, factory=Session):
        self.clock = Clock()
        self.core = factory(lambda: self.clock.mono)

    def stop_case(self):
        s = self.core
        s.begin_turn()
        stream = s.bind_player('synthetic-player')
        event = s.task('tts')
        s.send(event, name='answer', public='clue', answer='synthetic-answer',
               end=100, effect='picture', approved=True)
        ack = s.task('ack')
        s.interrupt()
        accepted = s.ack(ack, player='synthetic-player', stream=stream,
                         segment='answer', head=100)
        return {'old_ack': accepted, 'heard': s.context().get('heard'),
                'reveals': sum(c[0] == 'reveal' for c in s.drain_commands())}


def assert_stop(observed):
    # Independent literal expectation; adapter cannot supply its own oracle.
    if observed != {'old_ack': False, 'heard': (), 'reveals': 0}:
        raise AssertionError('cancelled answer committed')
