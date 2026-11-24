"""Deterministic, network-free doubles for future V2 adapters (not a product oracle)."""
from dataclasses import dataclass, field
import heapq
import math
import struct
import wave

DAY = 86400
SOURCE = 'synthetic-engineering-signal-not-speech'


class Clock:
    def __init__(self, utc=0):
        self.utc = utc
        self.mono = 0
        self.pending = []
        self.order = 0

    def after(self, delay, callback):
        if delay < 0:
            raise ValueError('negative delay')
        self.order += 1
        heapq.heappush(self.pending, (self.mono + delay, self.order, callback))

    def advance(self, seconds):
        if seconds < 0:
            raise ValueError('clock cannot reverse')
        end = self.mono + seconds
        while self.pending and self.pending[0][0] <= end:
            at, _, callback = heapq.heappop(self.pending)
            self.utc += at - self.mono
            self.mono = at
            callback()
        self.utc += end - self.mono
        self.mono = end


@dataclass(frozen=True)
class Event:
    connection: int = 1
    session: str = 'synthetic-session'
    turn: int = 1
    output: int = 1
    task: str = 'synthetic-task'
    sequence: int = 0
    kind: str = 'audio'


class Protocol:
    def __init__(self):
        self.current = Event()
        self.sequences = {}
        self.effects = []

    def accept(self, event):
        c = self.current
        if (event.connection, event.session, event.turn, event.output, event.task) != (
                c.connection, c.session, c.turn, c.output, c.task):
            return False
        if event.kind not in {'audio', 'model', 'image', 'tool', 'ack', 'safety', 'timer'}:
            return False
        key = (event.task, event.kind)
        if event.sequence != self.sequences.get(key, -1) + 1:
            return False
        self.sequences[key] = event.sequence
        self.effects.append(event.kind)
        return True

    def cancel(self):
        from dataclasses import replace
        self.current = replace(self.current, output=self.current.output + 1)
        self.sequences.clear()


class Handle:
    def __init__(self, cancel_fails=False, close_fails=False, capacity=2):
        self.cancel_fails, self.close_fails = cancel_fails, close_fails
        self.capacity = capacity
        self.queue = []
        self.muted = False
        self.unavailable = False

    def enqueue(self, item):
        if self.unavailable or len(self.queue) >= self.capacity:
            return False
        self.queue.append(item)
        return True

    def cancel(self):
        self.muted = True
        self.queue.clear()
        self.unavailable = self.cancel_fails or self.close_fails
        return not self.unavailable


class FaultBudget:
    """Network/quota/timeout injection with one retry and an immutable deadline."""
    def __init__(self, clock, budget=15):
        self.clock = clock
        self.deadline = clock.mono + budget
        self.retries = 0
        self.failed = False

    def fault(self, category, idempotent=True):
        if category not in {'network', 'quota', 'timeout', 'close'}:
            raise ValueError('unclassified injected fault')
        retry = (category in {'network', 'timeout'} and idempotent and self.retries == 0
                 and self.clock.mono < self.deadline and not self.failed)
        if retry:
            self.retries += 1
        else:
            self.failed = True
        return {'category': category, 'retry': retry, 'deadline': self.deadline}


class Playback:
    def __init__(self):
        self.stream = 0
        self.head = 0
        self.route = True
        self.sent = []
        self.confirmed = []

    def send(self, segment, end):
        if end <= (self.sent[-1][1] if self.sent else 0):
            raise ValueError('non-contiguous sample coordinates')
        self.sent.append((segment, end))

    def reset(self, reason):
        if reason not in {'flush', 'stop', 'rebuild', 'wrap', 'route-loss'}:
            raise ValueError(reason)
        self.stream += 1
        self.head = 0
        self.sent.clear()
        if reason == 'route-loss':
            self.route = False

    def ack(self, stream, segment, head):
        if stream != self.stream or not self.route or head < self.head or not self.sent:
            return False
        name, end = self.sent[0]
        if name != segment or head < end:
            return False
        self.head = head
        self.confirmed.append(name)
        self.sent.pop(0)
        return True


class Management:
    def __init__(self):
        self.epoch = 0
        self.page = 'idle'
        self.mic = False
        self.buffer = []
        self.context = []
        self.pair = 'synthetic-pair'
        self.used = set()

    def enter(self):
        self.epoch += 1
        self.page, self.mic = 'verify', True

    def exit(self):
        self.epoch += 1
        self.page, self.mic = 'idle', False
        self.buffer.clear()

    def command(self, epoch, command):
        if epoch != self.epoch or not self.mic:
            return False
        if command in {'exit', 'cancel'}:
            self.exit()
            return True
        return False

    def authenticate(self, token, operation, now):
        # Token is an injected test artifact, never a real authenticator.
        pair, op, epoch, challenge, expires, success = token
        if (not success or not pair or pair != self.pair or op != operation
                or epoch != self.epoch or now >= expires or challenge in self.used
                or self.page != 'verify'):
            return False
        self.used.add(challenge)
        return True


@dataclass
class Material:
    device: str
    created: int
    submitted: int | None = None
    withdrawal: int | None = None
    copies: set = field(default_factory=lambda: set(
        ['body', 'attachment', 'cache', 'index', 'download', 'note', 'replica', 'backup']))
    failed: set = field(default_factory=set)

    @property
    def expiry(self):
        original = self.submitted + 7 * DAY if self.submitted is not None else self.created + 3600
        return min(original, self.withdrawal + DAY) if self.withdrawal is not None else original

    def access(self, device, now):
        return device == self.device and self.withdrawal is None and now < self.expiry and bool(self.copies)

    def withdraw(self, now):
        if self.withdrawal is None:
            self.withdrawal = now

    def sweep(self, now):
        if self.withdrawal is not None or now >= self.expiry:
            self.copies.intersection_update(self.failed)
        return not self.copies

    def restore(self, now):
        # Immutable object expiry is needed even when deletion ledger has expired.
        if now >= self.expiry:
            self.copies.clear()
        return self.access(self.device, now)


def checked_effect(safety, kind):
    return safety is True and kind in {'audio', 'image', 'tool'}


def assert_no_body(artifacts, sentinel):
    for content in artifacts:
        if sentinel in content:
            raise AssertionError('synthetic body sentinel leaked')


def write_signal(path, rate=16000):
    """One second: silence, tone, pause, tone. No voice or ASR quality claim."""
    if rate != 16000:
        raise ValueError('fixture coordinates require 16kHz')
    with wave.open(str(path), 'wb') as output:
        output.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        output.writeframes(b''.join(struct.pack('<h', int(3000 * math.sin(2 * math.pi * 440 * i / rate)))
                                   if rate // 4 <= i < rate // 2 or 3 * rate // 4 <= i else b'\x00\x00'
                                   for i in range(rate)))
    return {'source': SOURCE, 'rate': rate, 'samples': rate,
            'intervals': [[0, 4000, 'silence'], [4000, 8000, 'tone'],
                          [8000, 12000, 'pause'], [12000, 16000, 'tone']]}
