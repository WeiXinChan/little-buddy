"""V2 in-memory full-duplex session adapter. No supplier or deployment defaults.

Providers are injected AFTER their privacy gate; the local fixture uses this exact
adapter. All Session mutations occur on the websocket event loop, never a worker.
"""
import asyncio
import base64
import json
import time
import sys
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from uuid import uuid4

from backend.v2.session import Identity, Session
from backend.v2.budget import ResponseBudget


class VoiceFault(Exception):
    """Supplier adapter must map verified errors; never infer quota from a timeout."""
    def __init__(self, code):
        if code not in {'quota', 'network', 'timeout', 'safety', 'voice'}:
            raise ValueError('failure classification')
        self.code = code
        super().__init__(code)


class WireError(ValueError):
    pass


def decode(raw):
    if not isinstance(raw, str) or len(raw.encode()) > 16000:
        raise WireError('frame')
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise WireError('duplicate')
            out[k] = v
        return out
    event = json.loads(raw, object_pairs_hook=pairs)
    schemas = {'heartbeat': set(), 'stop': {'intent'}, 'suspend': set(), 'resume_noise': set(),
               'input': {'pcm'}, 'seal': {'revision'}, 'probe': {'revision'}, 'advance': {'revision'},
               'wake': set(), 'wake_solo': set(), 'thinking_prompt': {'revision'}, 'bind': {'player'},
               'ack': {'identity', 'player', 'stream', 'segment', 'head'}, 'end': set()}
    if (not isinstance(event, dict) or event.get('v') != 2 or type(event.get('v')) is not int
            or event.get('type') not in schemas
            or (set(event) - ({'speech', 'age_ms'} if event['type'] == 'input' else {'age_ms'} if event['type'] == 'wake_solo' else set())) != schemas[event['type']] | {'v', 'type', 'epoch', 'seq'}
            or any(type(event[k]) is not int or event[k] < 0 for k in ('epoch', 'seq'))):
        raise WireError('schema')
    return event


class VoicePeer:
    def __init__(self, socket, providers, policy, *, clock=time.monotonic):
        self.socket, self.providers, self.policy = socket, providers, policy
        self.session = Session(clock)
        self.epoch, self.sequence = 0, -1
        self.capture = bytearray()
        self.input_budget = ResponseBudget(clock)
        self.awaiting_input = False
        self.generation = None
        self.recognition = None
        self.next_probe = None
        self.prepared = None
        self.revision = 0
        self.analysis = None
        self.prompted_revision = None
        self.quarantined = False
        self.suspended = False
        self.changed = asyncio.Event()
        self.ack_identity = None
        self.ack_sequence = 0
        self.send_sequence = 0
        self.closed = False

    @asynccontextmanager
    async def resource(self, manager):
        # Release failures and bounded cancellation are resource health failures,
        # never merely another retryable provider response.
        async with asyncio.timeout(4):
            value = await manager.__aenter__()
        try:
            yield value
        finally:
            exit_task = asyncio.create_task(manager.__aexit__(*sys.exc_info()))
            done, _ = await asyncio.wait({exit_task}, timeout=.5)
            if not done:
                self.quarantined = True
                exit_task.cancel()
                raise WireError('resource close timeout')
            if exit_task.cancelled() or exit_task.exception() is not None:
                self.quarantined = True
                raise WireError('resource close failure')

    async def send(self, kind, **fields):
        async with asyncio.timeout(2):
            await self.socket.send(json.dumps(dict(v=2, type=kind, epoch=self.epoch, **fields)))

    async def commands(self):
        for command in self.session.drain_commands():
            if command[0] == 'mute_flush':
                await self.send('revoke')
            elif command[0] == 'reveal':
                await self.send('reveal', effect=command[1], topic=command[2])
        self.changed.set()

    async def cancel_generation(self):
        task, self.generation = self.generation, None
        if task is not None:
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=.5)
            if not done:
                # Never reuse an unconfirmed provider resource. Connection closes;
                # caller/service owns eventual shutdown, no unbounded new attempts.
                self.quarantined = True
                raise WireError('provider close timeout')
            if not task.cancelled() and task.exception() is not None:
                self.quarantined = True
                raise WireError('provider close failure')

    async def handle(self, raw):
        event = decode(raw)
        kind, epoch, seq = event['type'], event['epoch'], event['seq']
        if epoch < self.epoch:
            return  # Revoked audio, ASR and playback callbacks have no effects.
        if epoch > self.epoch:
            if epoch != self.epoch + 1 or kind != 'stop' or seq != 0:
                raise WireError('epoch')
            self.epoch, self.sequence = epoch, -1
        if seq != self.sequence + 1:
            raise WireError('sequence')
        self.sequence = seq
        if kind == 'heartbeat':
            self.session.heartbeat()
        elif kind == 'stop':
            self.session.interrupt()
            self.capture.clear()
            self.suspended = False
            await self.commands()  # Local client already stopped before sending.
            await self.cancel_generation()
            prepared, self.prepared = self.prepared, None
            if prepared is not None and event['intent'] == prepared[2]:
                text, deadline, _, revision = prepared
                if revision != self.revision:
                    return
                if self.session.clock() >= deadline:
                    raise WireError("response budget exhausted")
                self.session.begin_turn()
                self.session.deadline = deadline
                self.awaiting_input = False
                await self.commands()
                await self.send('open', revision=self.revision)
                self.generation = asyncio.create_task(self.respond(text, self.epoch))
        elif kind == 'end':
            self.prepared = None
            if self.recognition is not None:
                self.recognition.cancel()
            self.session.clear()
            self.capture.clear()
            await self.commands()
            await self.cancel_generation()
        elif kind == 'suspend':
            self.suspended = True
        elif kind == 'resume_noise':
            self.suspended = False
            if self.session.player is None and self.generation is not None and not self.generation.done():
                await self.send('open', revision=self.revision)
            self.changed.set()
        elif kind == 'input':
            if self.quarantined:
                raise WireError('quarantined')
            data = base64.b64decode(event['pcm'], validate=True)
            if not data or len(data) % 2 or len(data) > 6400 or len(self.capture) + len(data) > 640000:
                raise WireError('capture capacity')
            speech, age = event.get('speech', True), event.get('age_ms', 0)
            if type(speech) is not bool or type(age) is not int or not 0 <= age <= 20000:
                raise WireError('capture boundary')
            if speech:
                self.input_budget.speech(age)
                self.awaiting_input = True
            self.capture.extend(data)
        elif kind == 'wake':
            self.session.valid_interaction()
        elif kind == 'wake_solo':
            if (not self.awaiting_input and self.prepared is None and not self.capture
                    and (self.generation is None or self.generation.done())):
                self.input_budget = ResponseBudget(self.session.clock)
                self.input_budget.speech(event.get('age_ms', 0))
                self.input_budget.remaining()
                self.awaiting_input = True
                await self.decision(None, 'new_turn', self.revision, self.input_budget.deadline)
        elif kind == 'advance':
            version = event['revision']
            if type(version) is not int or version != self.revision + 1:
                raise WireError('revision')
            self.revision = version
            self.suspended = True
            self.analysis = self.prepared = None
            self.session.valid_interaction()
            # Snapshot analysis can finish, but its old version cannot take effect.
        elif kind == 'probe':
            if event['revision'] != self.revision or not self.capture:
                return
            self.input_budget.resume()
            self.input_budget.remaining()
            if self.recognition is not None and not self.recognition.done():
                self.next_probe = (bytes(self.capture), self.epoch, self.revision)
                return
            self.recognition = asyncio.create_task(self.analyze(bytes(self.capture), self.epoch, self.revision))
        elif kind == 'thinking_prompt':
            if event['revision'] == self.revision and self.prompted_revision != self.revision:
                self.prompted_revision = self.revision
                # M05 may supply a contextual invitation. This event grants no
                # permission to seal or resume output, nor to make repeated prompts.
                await self.send('thinking_wait', revision=self.revision)
        elif kind == 'seal':
            if (event['revision'] != self.revision or self.analysis is None
                    or self.analysis[0] != self.revision or self.analysis[2] != 'complete'):
                return
            revision, text, _, meaning = self.analysis
            self.capture.clear()
            self.analysis = None
            self.input_budget.resume()
            self.input_budget.remaining()
            await self.decision(text, meaning, revision, self.input_budget.deadline)
        elif kind == 'bind':
            if (not isinstance(event['player'], str) or len(event['player']) > 128
                    or not event['player'] or self.session.player is not None or self.generation is None):
                raise WireError('player')
            stream = self.session.bind_player(event['player'])
            # reset_player commands belong to the pre-bind player; do not revoke
            # the just-created native track, which has not received audio yet.
            self.session.drain_commands()
            self.tts_identity = self.session.task('tts')
            self.ack_identity = self.session.task('ack')
            self.ack_sequence = self.send_sequence = 0
            await self.send('bound', player=event['player'], stream=stream,
                            identity=asdict(self.ack_identity))
            self.changed.set()
        elif kind == 'ack':
            try:
                identity = Identity(**event['identity'])
            except (TypeError, ValueError):
                raise WireError('identity') from None
            if (any(type(getattr(identity, k)) is not int for k in ('connection', 'turn', 'output', 'sequence'))
                    or not isinstance(identity.session, str) or not isinstance(identity.task, str)
                    or type(event['stream']) is not int or not isinstance(event['segment'], str)
                    or not isinstance(event['player'], str)):
                raise WireError('ack schema')
            self.session.ack(identity, player=event['player'], stream=event['stream'],
                             segment=event['segment'], head=event['head'])
            await self.commands()

    async def analyze(self, pcm, epoch, revision):
        session_id = self.session.session
        try:
            async with asyncio.timeout(self.input_budget.remaining()):
                async with self.resource(self.providers.recognize(16000)) as recognizer:
                    for offset in range(0, len(pcm), 6400):
                        await recognizer.write(pcm[offset:offset+6400])
                    text = await recognizer.finish()
                text = self.policy.input(text)
                # Async M05 unified-LLM contract. No fixed punctuation/word-count
                # shortcut treats a short word, recognition failure or echo as noise.
                result = await self.providers.endpoint(text, self.session.context())
                if (not isinstance(result, dict) or set(result) != {'completion', 'meaning'}
                        or result['completion'] not in {'complete', 'incomplete', 'thinking'}
                        or result['meaning'] not in {'new_turn', 'stop', 'noise', 'backchannel', 'thinking', 'unknown'}):
                    raise WireError('endpoint schema')
                if epoch != self.epoch or revision != self.revision or session_id != self.session.session or not self.session.active:
                    return
                self.input_budget.remaining()
                if result['completion'] == 'thinking':
                    self.input_budget.pause_thinking()
                self.analysis = (revision, text, result['completion'], result['meaning'])
                await self.send('endpoint', revision=revision, completion=result['completion'])
        except asyncio.CancelledError:
            raise
        except Exception:
            if epoch == self.epoch and revision == self.revision and session_id == self.session.session:
                await self.send('decision', meaning='unknown', intent='', revision=revision)
            if self.quarantined:
                await self.socket.close(1011, 'resource unavailable')
        finally:
            pcm = b''
            pending, self.next_probe = self.next_probe, None
            if pending is not None and not self.closed and pending[1:] == (self.epoch, self.revision):
                self.recognition = asyncio.create_task(self.analyze(*pending))

    async def decision(self, text, meaning, revision, deadline):
        if meaning == 'new_turn':
            intent = uuid4().hex
            self.prepared = (text, deadline, intent, revision)
        else:
            intent = ''
            self.awaiting_input = False
        await self.send('decision', meaning=meaning, intent=intent, revision=revision)

    async def compact_memory(self, epoch):
        if not hasattr(self.providers, 'compact'):
            return
        if max(len(self.session.public), len(self.session.private)) < 40 and len(self.session.revealed) < 80 and len(json.dumps(self.session.context(), ensure_ascii=False).encode()) < 24000:
            return
        snapshot = self.session.memory_snapshot(private=self.session.private_mode)
        keep = await self.providers.compact(snapshot[-1])
        if epoch != self.epoch:
            raise WireError('stale summary')
        self.session.compact(snapshot, keep)
        if len(self.session.revealed) >= 80:
            # Replays remain rejected by exact pending-front ID and task sequence.
            self.session.revealed.intersection_update(s.name for s in self.session.pending)

    async def respond(self, text, epoch):
        session_id = self.session.session
        stage = 'bind'
        try:
            while self.session.player is None:
                self.changed.clear()
                if not self.session._output_live():
                    return
                await self.changed.wait()
            # Unified model receives the authoritative played-only context. Supplier
            # adaptation belongs to M05; no unrestricted model-proposed facts enter it.
            await self.compact_memory(epoch)
            state = None
            if hasattr(self.providers, 'plan'):
                context = self.session.context()
                stage = 'plan'
                plan = await self.providers.plan(text, context)
                if epoch != self.epoch or not self.session._output_live():
                    return
                action = plan['action']
                if action == 'handoff' and any((self.session.recent, self.session.facts,
                                                         self.session.public, self.session.private,
                                                         self.session.game, self.session.secrets)):
                    old = self.session
                    deadline = old.deadline
                    old.handoff()
                    await self.commands()
                    if self.recognition is not None and not self.recognition.done():
                        self.recognition.cancel()
                    self.capture.clear()
                    self.analysis = self.next_probe = self.prepared = None
                    self.ack_identity = None
                    self.session = Session(old.clock, ttl=old.ttl, lease=old.lease, budget=old.budget,
                                           capacity=old.capacity, progress_timeout=old.progress_timeout)
                    # A normal client stop/epoch transition then binds a fresh track.
                    # The existing request keeps its original first-response deadline.
                    await self.decision(text, 'new_turn', self.revision, deadline)
                    return
                elif action == 'private':
                    self.session.private_mode = True
                elif action in {'change', 'leave'} and self.session.private_mode:
                    self.session.private_mode = False
                    plan = await self.providers.plan(text, self.session.context(shared=True))
                if action == 'leave':
                    plan.update(mode='chat', rules='', roles=[], secrets={})
                if epoch != self.epoch or not self.session._output_live():
                    return
                stage = 'facts'
                facts = await self.providers.facts(text)
                if epoch != self.epoch or not self.session._output_live():
                    return
                stage = 'fact_commit'
                self.session.record_input(text, facts)
                stage = 'safety'
                if not await self.providers.safe(''.join(plan['sentences']), self.session.context()):
                    raise WireError('safety')
                state = {k: plan[k] for k in ('mode', 'rules', 'roles', 'secrets')}
                @asynccontextmanager
                async def planned():
                    async def items():
                        for sentence in plan['sentences']:
                            if len(plan['sentences']) > 1 and not await self.providers.safe(sentence, self.session.context()):
                                raise WireError('safety')
                            yield sentence
                    yield items()
                manager = planned()
            else:
                manager = self.providers.answer(text, self.session.context())
            async with self.resource(manager) as sentences:
                sentence_number = 0
                async for proposed in sentences:
                    sentence_number += 1
                    if not isinstance(proposed, str) or len(proposed) > 2048:
                        raise WireError('text capacity')
                    approved = self.policy.segment(proposed)
                    if not approved:
                        raise WireError('policy')
                    stage = 'synthesis'
                    async with self.resource(self.providers.synthesize(approved, 24000)) as chunks:
                        # One-chunk lookahead marks the final chunk's public fact.
                        previous = None
                        async for chunk in chunks:
                            if not isinstance(chunk, bytes) or not chunk or len(chunk) % 2 or len(chunk) > 4800:
                                raise WireError('pcm capacity')
                            if previous is not None:
                                await self.audio(previous, '', epoch)
                            previous = chunk
                        if previous is None:
                            raise WireError('empty synthesis')
                        await self.audio(previous, approved, epoch,
                                         state=state if state is not None and sentence_number == len(plan['sentences']) else None,
                                         anchors=tuple(k for k, i in plan['anchors'].items() if i == sentence_number-1) if state is not None else ())
            while self.session.pending:
                self.changed.clear()
                if epoch != self.epoch or not self.session._output_live():
                    raise WireError('revoked')
                await self.changed.wait()
            self.session.deadline = 0
            await self.send('reply_end', head=self.session.head, public_facts=len(self.session.public))
        except asyncio.CancelledError:
            raise
        except Exception as failure:
            if epoch != self.epoch or session_id != self.session.session:
                return
            self.last_failure = dict(stage=stage, kind=type(failure).__name__)
            # Exception messages may contain provider content/credentials: never emit.
            self.session.interrupt()
            await self.commands()
            await self.send('failure', code=failure.code if isinstance(failure, VoiceFault) else 'timeout' if isinstance(failure, TimeoutError) else 'voice')
            if self.quarantined:
                await self.socket.close(1011, 'resource unavailable')
        finally:
            text = ''

    async def audio(self, pcm, public, epoch, state=None, anchors=()):
        while len(self.session.pending) >= 2 or self.suspended:
            self.changed.clear()
            if epoch != self.epoch or not self.session._output_live():
                raise WireError('revoked')
            await self.changed.wait()
        if epoch != self.epoch:
            raise WireError('revoked')
        await self.compact_memory(epoch)
        if epoch != self.epoch or not self.session._output_live():
            raise WireError('revoked')
        name, start = uuid4().hex, self.session.sent_end
        end = start + len(pcm)//2
        if not self.session.send(replace(self.tts_identity, sequence=self.send_sequence),
                                 name=name, public=public, end=end, approved=True, effective=True, state=state, anchors=anchors):
            raise WireError('send rejected')
        self.send_sequence += 1
        await self.send('audio', player=self.session.player, stream=self.session.stream,
                        segment=name, start=start, end=end, pcm=base64.b64encode(pcm).decode())

    async def monitor(self):
        while not self.closed:
            await asyncio.sleep(.1)
            if self.awaiting_input and self.input_budget.thinking_at is None:
                try:
                    self.input_budget.remaining()
                except (TimeoutError, ValueError):
                    self.session.interrupt()
                    await self.commands()
                    await self.cancel_generation()
                    if self.recognition is not None:
                        self.recognition.cancel()
                    await self.send('failure', code='timeout')
                    return
            self.session.poll()
            await self.commands()
            if not self.session.active or self.session.response_expired:
                await self.cancel_generation()
                await self.send('failure', code='timeout')
                return

    async def run(self):
        monitor = asyncio.create_task(self.monitor())
        receiver = None
        try:
            while self.session.active:
                receiver = asyncio.create_task(self.socket.recv())
                done, _ = await asyncio.wait({receiver, monitor}, return_when=asyncio.FIRST_COMPLETED)
                if monitor in done:
                    await monitor
                    break
                await self.handle(receiver.result())
        finally:
            self.closed = True
            for task in (monitor, receiver, self.recognition):
                if task is not None:
                    task.cancel()
            tasks = {t for t in (monitor, receiver, self.recognition) if t is not None}
            done, pending = await asyncio.wait(tasks, timeout=.5)
            for task in done:
                if not task.cancelled():
                    task.exception()
            if pending:
                self.quarantined = True
            self.session.clear()
            self.capture.clear()
            self.prepared = None
            self.analysis = self.next_probe = None
            await self.cancel_generation()
