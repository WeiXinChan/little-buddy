"""Single-owner deterministic session core for speech/LLM transports.

Call from one event loop per device. Clock must be monotonic. No persistence,
logging, networking or model authority is provided by this module.
"""
from dataclasses import dataclass
from collections import deque
import math
import json
import uuid
from hashlib import sha256
from copy import deepcopy
from .memory import partition, retrieve


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
    effective: bool
    state: dict | None = None
    private: bool = False
    anchors: tuple = ()


class Session:
    """Adapters own actual mute/cancel/release; drain commands after every call.

    ACK coordinates are engineering playback evidence, never acoustic evidence.
    Settings/pairing belong outside this object and survive clear().
    """
    def __init__(self, clock, *, ttl=600, lease=15, budget=15, capacity=2, progress_timeout=60):
        if any(not math.isfinite(x) or x <= 0 for x in (ttl, lease, budget, progress_timeout)):
            raise ValueError('invalid duration')
        if type(capacity) is not int or capacity < 1:
            raise ValueError('invalid capacity')
        self.clock, self.ttl, self.lease, self.budget = clock, ttl, lease, budget
        self.progress_timeout = progress_timeout
        self.response_confirmed = False
        self.response_expired = False
        self.progress_deadline = 0
        self.last_head_progress = clock()
        self.capacity = capacity
        self.connection = self.turn = self.output = self.stream = self.topic = 0
        self.session = uuid.uuid4().hex
        self.expires = clock() + ttl
        self.heartbeat_deadline = clock() + lease
        self.deadline = 0
        self.active = True
        self.public, self.private, self.secrets, self.game = [], [], {}, {}
        self.private_mode = False
        self.memory_revision = 0
        self.recent = []
        self.facts = {}
        self.source_archive = ''
        self.memory_limited = False
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
                     recent=self.recent, facts=self.facts, source_archive=self.source_archive,
                     memory_limited=self.memory_limited,
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
        self.memory_revision += 1
        self.public.clear()
        self.recent.clear(); self.facts.clear()
        self.source_archive='';self.memory_limited=False
        self.private_mode = False
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
        self.response_confirmed = self.response_expired = False
        self.progress_deadline = 0

    def interrupt(self):
        if self._live():
            self._revoke()

    def _output_live(self):
        if not self._live() or self.response_expired:
            return False
        limit = self.progress_deadline if self.response_confirmed else self.deadline
        if not limit or self.clock() >= limit:
            self._revoke()
            self.response_expired = True
            return False
        return True

    def task(self, name):
        if not isinstance(name, str) or not name or len(name) > 128:
            raise ValueError('invalid task ID')
        if not self._output_live() or name in self.tasks:
            raise RuntimeError('task unavailable')
        if len(self.tasks) >= self.capacity:
            raise BufferError('task capacity')
        self.tasks[name] = -1
        return Identity(self.connection, self.session, self.turn, self.output, name, 0)

    def accept(self, event):
        if not isinstance(event, Identity) or not self._output_live():
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
        if (not self._output_live() or self.response_confirmed or self.retry_used
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

    def send(self, event, *, name, public, end, approved, answer=None, effect=None,
             effective=True, state=None, anchors=()):
        if (not self._live() or approved is not True or self.player is None or type(end) is not int
                or end <= self.sent_end or len(self.pending) >= self.capacity
                or not all(isinstance(v, str) for v in (name, public))
                or (answer is not None and not isinstance(answer, str))
                or sum(len(v) for v in self.public) + sum(len(s.public) + len(s.answer or '') for s in self.pending)
                   + len(public) + len(answer or '') > self.content_limit
                or type(effective) is not bool
                or len(name) > 128 or len(self.revealed) + len(self.pending) >= 128
                or (effect is not None and (not isinstance(effect, str) or len(effect) > 128))
                or not name or name in self.revealed
                or any(s.name == name for s in self.pending)):
            return False
        if state is not None:
            if (not isinstance(state, dict) or set(state) != {'mode', 'rules', 'roles', 'secrets'} or
                    not isinstance(state['rules'], str) or not isinstance(state['roles'], list) or
                    not all(isinstance(x, str) for x in state['roles']) or
                    not isinstance(state['secrets'], dict) or
                    not all(isinstance(k, str) and isinstance(v, str) for k, v in state['secrets'].items()) or
                    state['mode'] not in {'chat', 'guess', 'story', 'adventure', 'association'}):
                return False
            state = deepcopy(state)
        if (not isinstance(anchors, tuple) or len(anchors) > 16 or
                any(not isinstance(k, str) or not 1 <= len(k) <= 40 for k in anchors)):
            return False
        candidate = Segment(name, public, answer, end, effect, effective, state, self.private_mode, anchors)
        if not self._fits(pending=[s.__dict__ for s in self.pending] + [candidate.__dict__]):
            return False
        if not self.accept(event):
            return False
        self.pending.append(candidate)
        self.sent_end = end
        return True

    def ack(self, event, *, player, stream, segment, head):
        if (not self._live() or player != self.player or stream != self.stream
                or type(head) is not int or head < self.head or head > self.sent_end
                or not self.pending or segment != self.pending[0].name):
            return False
        current = self.pending[0]
        if head >= current.end:
            public, private = list(self.public), list(self.private)
            target = private if current.private else public
            if current.public: target.append(current.public)
            if current.answer is not None: target.append(current.answer)
            recent = list(self.recent)
            if current.public:
                recent = (recent + [dict(text=current.public, role='played',
                                        turn=self.turn, private=current.private)])[-8:]
            facts = self._played_facts(current)
            game, secrets = self.game, self.secrets
            if current.state is not None and not current.private:
                game = deepcopy(current.state); secrets = game.pop('secrets')
            if not self._fits(public=public, private=private, recent=recent, facts=facts,
                              game=game, secrets=secrets,
                              pending=[s.__dict__ for s in list(self.pending)[1:]]):
                return False
        if not self.accept(event):
            return False
        advanced = head > self.head
        self.head = head
        if advanced:
            self.last_head_progress = self.clock()
        if self.response_confirmed and advanced:
            self.progress_deadline = self.clock() + self.progress_timeout
        if head < current.end:
            self.uncertain.add(segment)
            return False
        self.pending.popleft()
        if current.effective and not self.response_confirmed:
            self.response_confirmed = True
            self.progress_deadline = self.last_head_progress + self.progress_timeout
        self.uncertain.discard(segment)
        target = self.private if current.private else self.public
        if current.public:
            target.append(current.public)
            self.recent = (self.recent + [dict(text=current.public, role='played',
                                             turn=self.turn, private=current.private)])[-8:]
            self.memory_revision += 1
        if current.public:
            self.facts = self._played_facts(current)
        if current.answer is not None:
            target.append(current.answer)
            self.memory_revision += 1
        if current.state is not None and not current.private:
            proposed = deepcopy(current.state)
            self.secrets = proposed.pop('secrets')
            self.game = proposed
            self.topic += 1
        if current.public or current.answer is not None or current.effect:
            self.revealed.add(segment)
        if current.effect:
            if current.effect.startswith('image:'):
                self.commands.append(('reveal', current.effect, self.topic,current.name,current.end))
            else:
                self.commands.append(('reveal', current.effect, self.topic))
        return True

    def _played_facts(self, current):
        facts = deepcopy(self.facts)
        prefix = 'private:played:' if current.private else 'public:played:'
        for key in current.anchors:
            name = prefix + key
            facts.pop(name, None)
            facts[name] = dict(value=current.public, source='played',
                               segment=current.name, turn=self.turn, private=current.private)
        # Current facts by semantic key supersede old values. Old output anchors
        # are bounded per visibility; recent utterances and current game remain.
        owned = [k for k in facts if k.startswith(prefix)]
        protected = {'plot.main', 'plot.goal', 'plot.location', 'plot.inventory',
                     'clue.current', 'answer.current', 'rule.current', 'role.current', 'promise.current'}
        removable = [k for k in owned if k[len(prefix):] not in protected]
        for key in removable[:max(0, len(owned)-16)]:
            del facts[key]
        return facts

    def record_input(self, text, facts):
        if text is None:
            return
        if not self._live() or not isinstance(text, str) or len(text) > 2048:
            raise ValueError('input')
        if not isinstance(facts, list) or len(facts) > 8:
            raise ValueError('facts')
        candidate = deepcopy(self.facts)
        for fact in facts:
            if (not isinstance(fact, dict) or set(fact) not in ({'key', 'start', 'end', 'value'}, {'key', 'start', 'end', 'value', 'dimension'}) or
                    fact['key'] not in {'nickname', 'preference', 'role', 'rule', 'clue', 'plot', 'promise'} or
                    type(fact['start']) is not int or type(fact['end']) is not int or
                    not 0 <= fact['start'] < fact['end'] <= len(text) or
                    fact['value'] != text[fact['start']:fact['end']] or len(fact['value']) > 256):
                raise ValueError('fact provenance')
            dimension = fact.get('dimension', 'unspecified')
            if dimension not in {'unspecified', 'animal', 'color', 'food', 'sport', 'activity',
                                  'music', 'place', 'person', 'object', 'other'}:
                raise ValueError('fact dimension')
            # Public and private versions cannot overwrite each other.
            key = ('private:' if self.private_mode else 'public:') + fact['key']
            source_id = sha256(json.dumps([text, fact['key'], dimension,
                                           fact['start'], fact['end']], ensure_ascii=False).encode()).hexdigest()
            previous = candidate.get(key)
            if previous is not None and previous.get('source_id') != source_id:
                prior_id = previous.get('source_id') or sha256(previous['source_text'].encode()).hexdigest()
                candidate[key + ':history:' + prior_id] = previous
            candidate[key] = dict(value=fact['value'], source='child', turn=self.turn,
                                  source_text=text, span=[fact['start'], fact['end']],
                                  source_id=source_id, dimension=dimension,
                                  evidence_only=True, private=self.private_mode)
        recent = (self.recent + [dict(text=text, role='child', turn=self.turn, private=self.private_mode)])[-8:]
        try:
            candidate,archive=partition(candidate,self.source_archive)
        except BufferError:
            archive=None
        if archive is None or not self._fits(facts=candidate,recent=recent,source_archive=archive,
                                             reply_reserve=' '*8192):
            # Preserve accepted evidence. A full memory must not kill the turn
            # or silently replace old claims. Surface the coverage limit to the
            # planner, keep the new input in a bounded recent window, and ask
            # for confirmation rather than claiming unavailable recollection.
            self.memory_limited=True
            while recent and not self._fits(recent=recent):recent=recent[1:]
            self.recent=recent
            self.memory_revision+=1
            return False
        self.facts = candidate
        self.source_archive = archive
        self.recent = recent
        self.memory_revision += 1
        return True

    def memory_snapshot(self, *, private=False):
        return (self.connection, self.session, self.turn, self.output, self.memory_revision,
                private, tuple(self.private if private else self.public))

    def compact(self, snapshot, keep):
        # Extractive writeback only: no prose and no proposed/unplayed facts.
        if not self._live() or snapshot != self.memory_snapshot(private=snapshot[-2]):
            return False
        facts = snapshot[-1]
        if (not isinstance(keep, list) or any(type(i) is not int or not 0 <= i < len(facts) for i in keep)
                or len(set(keep)) != len(keep)):
            return False
        selected = [facts[i] for i in sorted(keep)]
        # Always keep the recent conversational tail, independent of model advice.
        selected = list(dict.fromkeys(selected + list(facts[-8:])))
        if facts and not selected:
            return False
        if len(selected) >= len(facts):
            return False
        if snapshot[-2]:
            self.private = selected
        else:
            self.public = selected
        self.memory_revision += 1
        # Old IDs cannot be ACKed: pending first-segment + sequence + stream gate.
        self.revealed.intersection_update(s.name for s in self.pending)
        return True

    def image_ready(self, event, *, topic):
        # Readiness is deliberately not a reveal command.
        return topic == self.topic and self.accept(event)

    def change_game(self, *, rules, roles, secrets):
        if not self._live():
            return False
        # Validate and detach every candidate before changing cancellation/topic state.
        if (not isinstance(rules, str) or not isinstance(roles, (list, tuple))
                or not all(isinstance(role, str) for role in roles)
                or not isinstance(secrets, dict)
                or not all(isinstance(k, str) and isinstance(v, str) for k, v in secrets.items())):
            raise TypeError('rules/roles/secrets schema')
        candidate_game = deepcopy({'rules': rules, 'roles': roles})
        candidate_secrets = deepcopy(dict(secrets))
        if not self._fits(game=candidate_game, secrets=candidate_secrets):
            raise BufferError('game context capacity or invalid data')
        self._revoke()
        self.topic += 1
        self.game = candidate_game
        self.secrets = candidate_secrets
        return True

    def remember_private(self, text):
        if not isinstance(text, str):
            raise ValueError('private text required')
        if self._live():
            if not self._fits(private=self.private + [text]):
                raise BufferError('private context capacity')
            self.private.append(text)

    def context(self, *, shared=False, query=''):
        if not self._live():
            return {}
        # No arbitrary model-authored summary can promote proposed facts.
        facts,coverage=retrieve(self.facts,self.source_archive,query,not shared and self.private_mode)
        coverage['capacity_limited']=self.memory_limited
        return {'heard': tuple(self.public), 'game': deepcopy(self.game),
                'recent': deepcopy([r for r in self.recent if (not shared and self.private_mode) or not r['private']]),
                'facts': deepcopy(facts), 'memory':coverage,
                'unrevealed': {} if shared else deepcopy(self.secrets),
                'private': tuple(self.private) if self.private_mode and not shared else (),
                'partial_unknown': tuple(sorted(self.uncertain))}

    def handoff(self):
        self.clear()
        # Caller allocates a new Session; closed IDs can never be resumed.

    def poll(self):
        if self._live() and self.deadline:
            self._output_live()
        return self.active
