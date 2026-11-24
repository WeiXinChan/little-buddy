"""Single-owner deterministic session core for speech/LLM transports.

Call from one event loop per device. Clock must be monotonic. No persistence,
logging, networking or model authority is provided by this module.
"""
from dataclasses import dataclass
from collections import deque
import math
import json
import uuid
from copy import deepcopy


@dataclass(frozen=True)
class Identity:
    connection: int
    session: str
    turn: int
    output: int
    task: str
    sequence: int


@dataclass(frozen=True)
class Segment:
    name: str
    public: str
    answer: str | None
    end: int
    effect: str | None


class Session:
    """Adapters own actual mute/cancel/release; drain commands after every call.

    ACK coordinates are engineering playback evidence, never acoustic evidence.
    Settings/pairing belong outside this object and survive clear().
    """
    def __init__(self, clock, *, ttl=600, lease=15, budget=15, capacity=2):
        if any(not math.isfinite(x) or x <= 0 for x in (ttl, lease, budget)):
            raise ValueError('invalid duration')
        if type(capacity) is not int or capacity < 1:
            raise ValueError('invalid capacity')
        self.clock, self.ttl, self.lease, self.budget = clock, ttl, lease, budget
        self.capacity = capacity
        self.connection = self.turn = self.output = self.stream = self.topic = 0
        self.session = uuid.uuid4().hex
        self.expires = clock() + ttl
        self.heartbeat_deadline = clock() + lease
        self.deadline = 0
        self.active = True
        self.public, self.private, self.secrets, self.game = [], [], {}, {}
        self.pending = deque()
        self.tasks, self.commands = {}, deque()
        self.player = None
        self.head = self.sent_end = 0
        self.revealed, self.uncertain = set(), set()
        self.retry_used = False
        self.content_limit = 65536

    def _live(self):
        if self.active and self.clock() >= min(self.expires, self.heartbeat_deadline):
            self.clear()
        return self.active

    def drain_commands(self):
        result = tuple(self.commands)
        self.commands.clear()
        return result

    def valid_interaction(self):
        """Only confirmed child interaction; never heartbeat or management."""
        if not self._live():
            return False
        self.expires = self.clock() + self.ttl
        return True

    def _fits(self, **changes):
        state = dict(public=self.public, private=self.private, game=self.game, secrets=self.secrets,
                     pending=[s.__dict__ for s in self.pending])
        state.update(changes)
        try:
            return len(json.dumps(state, ensure_ascii=False).encode()) <= self.content_limit
        except (TypeError, ValueError):
            return False

    def _revoke(self):
        if len(self.commands) + len(self.tasks) + 1 > 128:
            raise BufferError("drain control commands before more mutations")
        self.output += 1
        self.commands.append(('mute_flush', self.output))
        for task in self.tasks:
            self.commands.append(('cancel_release', task))
        self.tasks.clear()
        self.uncertain.update(s.name for s in self.pending)
        if len(self.uncertain) > 128:
            self.uncertain = set(sorted(self.uncertain)[-128:])
        self.pending.clear()
        self.player = None
        self.stream += 1
        self.head = self.sent_end = 0

    def clear(self):
        if self.active:
            self._revoke()
        self.active = False
        self.public.clear()
        self.private.clear()
        self.secrets.clear()
        self.game.clear()
        self.uncertain.clear()
        self.revealed.clear()

    def heartbeat(self):
        if self._live():
            self.heartbeat_deadline = self.clock() + self.lease
            return True
        return False

    def reconnect(self):
        if not self._live():
            return False
        self._revoke()
        self.connection += 1
        return True

    def begin_turn(self):
        if not self._live():
            raise RuntimeError('session closed')
        self.valid_interaction()
        self._revoke()
        self.turn += 1
        self.deadline = self.clock() + self.budget
        self.retry_used = False

    def interrupt(self):
        if self._live():
            self._revoke()

    def task(self, name):
        if not isinstance(name, str) or not name or len(name) > 128:
            raise ValueError('invalid task ID')
        if not self._live() or self.clock() >= self.deadline or name in self.tasks:
            raise RuntimeError('task unavailable')
        if len(self.tasks) >= self.capacity:
            raise BufferError('task capacity')
        self.tasks[name] = -1
        return Identity(self.connection, self.session, self.turn, self.output, name, 0)

    def accept(self, event):
        if not isinstance(event, Identity) or not self._live():
            return False
        if self.clock() >= self.deadline:
            self._revoke()
            return False
        if (event.connection, event.session, event.turn, event.output) != (
                self.connection, self.session, self.turn, self.output):
            return False
        if (any(type(v) is not int for v in (event.connection, event.turn, event.output, event.sequence))
                or event.task not in self.tasks):
            return False
        if event.sequence != self.tasks[event.task] + 1:
            return False
        self.tasks[event.task] = event.sequence
        return True

    def retry(self, *, safe, idempotent):
        if (not self._live() or self.clock() >= self.deadline or self.retry_used
                or safe is not True or idempotent is not True):
            return False
        self._revoke()
        self.retry_used = True
        return True

    def bind_player(self, handle):
        if not self._live() or not handle:
            raise RuntimeError('player unavailable')
        self.reset_player('rebuild')
        self.player = handle
        return self.stream

    def reset_player(self, reason):
        if reason not in {'flush', 'stop', 'rebuild', 'wrap', 'route-loss'}:
            raise ValueError('unknown reset')
        self._revoke()

    def send(self, event, *, name, public, end, approved, answer=None, effect=None):
        if (not self._live() or approved is not True or self.player is None or type(end) is not int
                or end <= self.sent_end or len(self.pending) >= self.capacity
                or not all(isinstance(v, str) for v in (name, public))
                or (answer is not None and not isinstance(answer, str))
                or sum(len(v) for v in self.public) + sum(len(s.public) + len(s.answer or '') for s in self.pending)
                   + len(public) + len(answer or '') > self.content_limit
                or len(name) > 128 or len(self.revealed) >= 128
                or (effect is not None and (not isinstance(effect, str) or len(effect) > 128))
                or not name or name in self.revealed
                or any(s.name == name for s in self.pending)):
            return False
        candidate = Segment(name, public, answer, end, effect)
        if not self._fits(pending=[s.__dict__ for s in self.pending] + [candidate.__dict__]):
            return False
        if not self.accept(event):
            return False
        self.pending.append(Segment(name, public, answer, end, effect))
        self.sent_end = end
        return True

    def ack(self, event, *, player, stream, segment, head):
        if (not self._live() or player != self.player or stream != self.stream
                or type(head) is not int or head < self.head or head > self.sent_end
                or not self.pending or segment != self.pending[0].name):
            return False
        current = self.pending[0]
        if not self.accept(event):
            return False
        self.head = head
        if head < current.end:
            self.uncertain.add(segment)
            return False
        self.pending.popleft()
        self.uncertain.discard(segment)
        self.public.append(current.public)
        if current.answer is not None:
            self.public.append(current.answer)
        self.revealed.add(segment)
        if current.effect:
            self.commands.append(('reveal', current.effect, self.topic))
        return True

    def image_ready(self, event, *, topic):
        # Readiness is deliberately not a reveal command.
        return topic == self.topic and self.accept(event)

    def change_game(self, *, rules, roles, secrets):
        if not self._live():
            return False
        if not self._fits(game={'rules': rules, 'roles': roles}, secrets=secrets):
            raise BufferError('game context capacity or invalid data')
        self._revoke()
        self.topic += 1
        self.game = deepcopy({'rules': rules, 'roles': roles})
        self.secrets = deepcopy(dict(secrets))
        return True

    def remember_private(self, text):
        if not isinstance(text, str):
            raise ValueError('private text required')
        if self._live():
            if not self._fits(private=self.private + [text]):
                raise BufferError('private context capacity')
            self.private.append(text)

    def context(self, *, shared=False):
        if not self._live():
            return {}
        # No arbitrary model-authored summary can promote proposed facts.
        return {'heard': tuple(self.public), 'game': deepcopy(self.game),
                'unrevealed': {} if shared else deepcopy(self.secrets),
                'private': () if shared else tuple(self.private),
                'partial_unknown': tuple(sorted(self.uncertain))}

    def handoff(self):
        self.clear()
        # Caller allocates a new Session; closed IDs can never be resumed.

    def poll(self):
        if self._live() and self.deadline and self.clock() >= self.deadline:
            self._revoke()
            self.deadline = 0
        return self.active
