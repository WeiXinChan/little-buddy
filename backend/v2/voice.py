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
from backend.v2.safety import SafetyFault, local_help
from backend.v2.images import revealable


class VoiceFault(Exception):
    """Supplier adapter must map verified errors; never infer quota from a timeout."""
    def __init__(self, code):
        if code not in {'quota', 'network', 'timeout', 'safety', 'voice'}:
            raise ValueError('failure classification')
        self.code = code
        super().__init__(code)


class WireError(ValueError):
    pass


class StaleOperation(asyncio.CancelledError):
    """Revoked work cannot dispatch, publish, or borrow another session."""


class Operation:
    def __init__(self, peer, epoch, revision=None):
        self.peer, self.session = peer, peer.session
        self.session_id = self.session.session
        self.connection, self.turn = self.session.connection, self.session.turn
        self.epoch, self.revision = epoch, revision
        self.budget = peer.input_budget
        self.output = None
        self.cancelled = False

    def valid(self):
        p, s = self.peer, self.session
        return (not self.cancelled and not p.closed and not p.quarantined
                and p.session is s and s.session == self.session_id
                and p.epoch == self.epoch and s.connection == self.connection
                and s.turn == self.turn
                and (self.revision is None or p.revision == self.revision)
                and (self.output is None or s.output == self.output)
                and s._live())

    def ensure(self):
        task = asyncio.current_task()
        if not self.valid() or (task is not None and task.cancelling()):
            raise StaleOperation()



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
            or (set(event) - ({'speech', 'age_ms'} if event['type'] == 'input' else {'age_ms'} if event['type'] == 'wake_solo' else {'features'} if event['type'] == 'bind' else set())) != schemas[event['type']] | {'v', 'type', 'epoch', 'seq'}
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
        self.images_enabled = False
        self.prepared_visual = None
        self.visual_task = None
        self.recognition_scopes = {}
        self.generation_scopes = {}
        self.retired_tasks = set()

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
            self.track_retired(exit_task)
            try:
                done, _ = await asyncio.wait({exit_task}, timeout=.5)
            except asyncio.CancelledError:
                # The caller stopping must not orphan an unconfirmed close.
                self.quarantined = True
                exit_task.cancel()
                raise
            if not done:
                self.quarantined = True
                exit_task.cancel()
                raise WireError('resource close timeout')
            if exit_task.cancelled() or exit_task.exception() is not None:
                self.quarantined = True
                raise WireError('resource close failure')

    async def owned(self, operation, function, *args, **kwargs):
        operation.ensure()
        result = await function(*args, **kwargs)
        operation.ensure()
        return result

    @asynccontextmanager
    async def owned_resource(self, operation, factory, *args):
        operation.ensure()
        async with self.resource(factory(*args)) as value:
            operation.ensure()
            yield value
        operation.ensure()

    async def owned_items(self, operation, source):
        operation.ensure()
        iterator = source.__aiter__()
        while True:
            try:
                yield await self.owned(operation, iterator.__anext__)
            except StopAsyncIteration:
                return

    def track_retired(self, task):
        self.retired_tasks.add(task)
        def finished(done):
            self.retired_tasks.discard(done)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)

    async def cancel_recognition(self):
        task = self.recognition
        self.next_probe = None
        if task is None or task.done():
            return
        scope = self.recognition_scopes.get(task)
        if scope is not None:
            scope.cancelled = True
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=.5)
        if not done:
            # No replacement supplier is allowed on this connection after an
            # unconfirmed release. Late work still retains its revoked scope.
            self.quarantined = True
            self.track_retired(task)
        elif not task.cancelled():
            task.exception()

    async def close_quarantined(self):
        task = asyncio.create_task(self.socket.close(1011, 'resource unavailable'))
        done, _ = await asyncio.wait({task}, timeout=.5)
        if not done:
            task.cancel()
            self.track_retired(task)
        elif not task.cancelled():
            task.exception()

    async def send(self, kind, **fields):
        if kind in {'bound', 'open'}:
            # Establish scope on normal authenticated control frames, never learn it from a fault.
            fields.setdefault('session', self.session.session)
            fields.setdefault('turn', self.session.turn)
            fields.setdefault('revision', self.revision)
        async with asyncio.timeout(2):
            await self.socket.send(json.dumps(dict(v=2, type=kind, epoch=self.epoch, **fields)))

    async def commands(self):
        session, epoch, turn = self.session, self.epoch, self.session.turn
        for command in session.drain_commands():
            if self.session is not session or self.epoch != epoch or session.turn != turn:
                break
            if command[0] == 'mute_flush':
                self.invalidate_visual()
                await self.send('revoke')
            elif command[0] == 'reveal':
                if command[1].startswith('image:'):
                    prepared=self.prepared_visual
                    if (prepared is not None and command[1]=='image:'+prepared['token'] and
                        self.visual_live(prepared) and command[2]==prepared['topic'] and len(command)==5):
                        prepared['played']=(command[3],command[4])
                        await self.reveal_visual(prepared)
                else:
                    await self.send('reveal', effect=command[1], topic=command[2])
        self.changed.set()

    def visual_live(self, value):
        return (self.images_enabled and not self.closed and self.session._live() and value['session']==self.session.session and
                value['turn']==self.session.turn and value['revision']==self.revision and
                value['epoch']==self.epoch and value['output']==self.session.output)

    def invalidate_visual(self):
        self.prepared_visual=None
        task,self.visual_task=self.visual_task,None
        if task is not None and not task.done():
            task.cancel();self.track_retired(task)

    async def prepare_visual(self, prepared, request, operation):
        owner=asyncio.current_task()
        try:
            image=await self.owned(operation,self.providers.prepare_visual,request)
            if self.prepared_visual is not prepared or not self.visual_live(prepared) or image is None:return
            if prepared['answer_asset'] is not None and image.asset_id!=prepared['answer_asset']:return
            prepared['ready']=image.payload()
            fields={k:prepared[k] for k in ('session','turn','revision','topic','token')}
            await self.send('image_ready',**fields,**prepared['ready'])
            if self.prepared_visual is prepared and self.visual_live(prepared):await self.reveal_visual(prepared)
        except (StaleOperation,asyncio.CancelledError):
            return
        except Exception:
            if self.prepared_visual is prepared:self.prepared_visual=None
        finally:
            if self.visual_task is owner:self.visual_task=None

    async def reveal_visual(self, prepared):
        if (self.prepared_visual is not prepared or not self.visual_live(prepared) or
            prepared['ready'] is None or prepared['played'] is None or prepared['topic']!=self.session.topic):return
        self.prepared_visual=None # consume before transport can yield
        fields={k:prepared[k] for k in ('session','turn','revision','topic','token')}
        await self.send('reveal',effect='image:'+prepared['token'],**fields,
            asset_id=prepared['ready']['asset_id'],sha256=prepared['ready']['sha256'],
            player=self.session.player,stream=self.session.stream,
            segment=prepared['played'][0],end=prepared['played'][1])

    async def hide_visual(self, reason):
        self.invalidate_visual()
        if self.images_enabled:
            await self.send('hide', session=self.session.session,turn=self.session.turn,
                            revision=self.revision,topic=self.session.topic,reason=reason)

    async def cancel_generation(self):
        task, self.generation = self.generation, None
        if task is not None:
            scope = self.generation_scopes.get(task)
            if scope is not None:
                scope.cancelled = True
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=.5)
            if not done:
                # Never reuse an unconfirmed provider resource. Connection closes;
                # caller/service owns eventual shutdown, no unbounded new attempts.
                self.quarantined = True
                self.track_retired(task)
                raise WireError('provider close timeout')
            if not task.cancelled() and task.exception() is not None:
                self.quarantined = True
                raise WireError('provider close failure')

    async def handle(self, raw):
        event = decode(raw)
        if self.quarantined and event['type'] != 'end':
            raise WireError('quarantined')
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
            self.session.clear()
            self.capture.clear()
            await self.cancel_recognition()
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
            await self.hide_visual('input_changed')
            self.analysis = self.prepared = None
            self.session.valid_interaction()
            # Snapshot analysis can finish, but its old version cannot take effect.
        elif kind == 'probe':
            if event['revision'] != self.revision or not self.capture:
                return
            self.input_budget.resume()
            self.input_budget.remaining()
            if self.recognition is not None and not self.recognition.done():
                self.next_probe = (bytes(self.capture), Operation(self, self.epoch, self.revision), self.recognition)
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
            features=event.get('features',[])
            if not isinstance(features,list) or len(features)>1 or any(x!='images_v1' for x in features):
                raise WireError('features')
            self.images_enabled='images_v1' in features
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

    def analyze(self, pcm, epoch, revision):
        # Bind on invocation, before create_task can be delayed until a handoff.
        return self._analyze(pcm, Operation(self, epoch, revision))

    async def _analyze(self, pcm, operation):
        owner = asyncio.current_task()
        self.recognition_scopes[owner] = operation
        try:
            operation.ensure()
            async with asyncio.timeout(operation.budget.remaining()):
                async with self.owned_resource(operation, self.providers.recognize, 16000) as recognizer:
                    for offset in range(0, len(pcm), 6400):
                        await self.owned(operation, recognizer.write, pcm[offset:offset+6400])
                    text = await self.owned(operation, recognizer.finish)
                operation.ensure()
                text = self.policy.input(text)
                operation.ensure()
                # Only this operation's authorised session may supply context.
                context = operation.session.context()
                result = await self.owned(operation, self.providers.endpoint, text, context)
                if (not isinstance(result, dict) or set(result) != {'completion', 'meaning'}
                        or result['completion'] not in {'complete', 'incomplete', 'thinking'}
                        or result['meaning'] not in {'new_turn', 'stop', 'noise', 'backchannel', 'thinking', 'unknown'}):
                    raise WireError('endpoint schema')
                operation.ensure()
                operation.budget.remaining()
                if result['completion'] == 'thinking':
                    operation.budget.pause_thinking()
                self.analysis = (operation.revision, text, result['completion'], result['meaning'])
                await self.owned(operation, self.send, 'endpoint',
                                 revision=operation.revision, completion=result['completion'])
        except StaleOperation:
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            if operation.valid():
                await self.owned(operation, self.send, 'decision', meaning='unknown',
                                 intent='', revision=operation.revision)
        finally:
            pcm = b''
            self.recognition_scopes.pop(owner, None)
            # An old finally must not consume a newer owner's pending probe.
            pending = self.next_probe
            if self.recognition is owner and pending is not None and pending[2] is owner:
                self.next_probe = None
                data, following, _ = pending
                if following.valid() and not operation.cancelled and not owner.cancelling():
                    self.recognition = asyncio.create_task(self._analyze(data, following))

    async def decision(self, text, meaning, revision, deadline):
        if meaning == 'new_turn':
            intent = uuid4().hex
            self.prepared = (text, deadline, intent, revision)
        else:
            intent = ''
            self.awaiting_input = False
        await self.send('decision', meaning=meaning, intent=intent, revision=revision)

    async def compact_memory(self, epoch, operation=None):
        operation = operation or Operation(self, epoch)
        operation.ensure()
        if not hasattr(self.providers, 'compact'):
            return
        if max(len(self.session.public), len(self.session.private)) < 40 and len(self.session.revealed) < 80 and len(json.dumps(self.session.context(), ensure_ascii=False).encode()) < 24000:
            return
        snapshot = self.session.memory_snapshot(private=self.session.private_mode)
        keep = await self.owned(operation, self.providers.compact, snapshot[-1])
        if epoch != self.epoch:
            raise WireError('stale summary')
        self.session.compact(snapshot, keep)
        if len(self.session.revealed) >= 80:
            # Replays remain rejected by exact pending-front ID and task sequence.
            self.session.revealed.intersection_update(s.name for s in self.session.pending)

    async def review(self, operation, text):
        try:
            verdict = await self.owned(operation, self.providers.safe, text, operation.session.context())
        except SafetyFault:
            raise
        except Exception:
            raise SafetyFault('review_unavailable') from None
        if verdict is not True:
            raise SafetyFault('content_blocked' if verdict is False else 'review_unavailable')

    def respond(self, text, epoch):
        return self._respond(text, epoch, Operation(self, epoch))

    async def _respond(self, text, epoch, operation):
        owner = asyncio.current_task()
        self.generation_scopes[owner] = operation
        stage = 'bind'
        response_revision = self.revision
        try:
            operation.ensure()
            while self.session.player is None:
                self.changed.clear()
                if not self.session._output_live():
                    return
                await self.owned(operation, self.changed.wait)
            operation.output = self.session.output
            operation.ensure()
            # Unified model receives the authoritative played-only context. Supplier
            # adaptation belongs to M05; no unrestricted model-proposed facts enter it.
            await self.compact_memory(epoch, operation)
            state = None
            image_effect=None; answer_public=False
            stage = 'input_policy'
            if getattr(self.policy, 'needs_local_help', lambda _: False)(text) is True:
                raise SafetyFault('content_blocked')
            if hasattr(self.providers, 'plan'):
                context = self.session.context(query=text or '')
                if self.images_enabled and hasattr(self.providers,'image_catalogue'):
                    context['image_catalog']=self.providers.image_catalogue()
                stage = 'plan'
                plan = await self.owned(operation, self.providers.plan, text, context)
                if epoch != self.epoch or not self.session._output_live():
                    return
                action = plan['action']
                if action == 'handoff' and any((self.session.recent, self.session.facts,
                                                         self.session.public, self.session.private,
                                                         self.session.game, self.session.secrets)):
                    old = self.session
                    deadline = old.deadline
                    transition_revision = self.revision
                    old.handoff()
                    await self.commands()
                    await self.cancel_recognition()
                    if (self.session is not old or epoch != self.epoch or old.turn != operation.turn
                            or self.revision != transition_revision or self.closed
                            or asyncio.current_task().cancelling()):
                        return
                    self.capture.clear()
                    self.analysis = self.next_probe = self.prepared = None
                    self.ack_identity = None
                    self.session = Session(old.clock, ttl=old.ttl, lease=old.lease, budget=old.budget,
                                           capacity=old.capacity, progress_timeout=old.progress_timeout)
                    # A normal client stop/epoch transition then binds a fresh track.
                    # The existing request keeps its original first-response deadline.
                    if self.quarantined:
                        await self.send('failure', code='voice')
                        await self.close_quarantined()
                        return
                    await self.decision(text, 'new_turn', self.revision, deadline)
                    return
                elif action == 'private':
                    self.session.private_mode = True
                elif action in {'change', 'leave'} and self.session.private_mode:
                    self.session.private_mode = False
                    plan = await self.owned(operation, self.providers.plan, text, operation.session.context(shared=True,query=text or ''))
                if action == 'leave':
                    plan.update(mode='chat', rules='', roles=[], secrets={})
                if epoch != self.epoch or not self.session._output_live():
                    return
                stage = 'facts'
                facts = await self.owned(operation, self.providers.facts, text)
                if epoch != self.epoch or not self.session._output_live():
                    return
                stage = 'fact_commit'
                accepted=self.session.record_input(text, facts)
                if accepted is False:
                    # A real storage bound is a normal conversational branch,
                    # not a provider failure or a license to invent recollection.
                    plan.update(sentences=['我这会儿记不全前面的细节，请再告诉我这次最重要的事，我们接着玩。'],anchors={},tools=[])
                    plan.update(mode=self.session.game.get('mode','chat'),
                                rules=self.session.game.get('rules',''),roles=self.session.game.get('roles',[]),
                                secrets=dict(self.session.secrets))
                stage = 'safety'
                await self.review(operation, ''.join(plan['sentences']))
                state = {k: plan[k] for k in ('mode', 'rules', 'roles', 'secrets')}
                image_effect=None; answer_public=False
                tools=plan.get('tools',[])
                if self.images_enabled and tools:
                    request=tools[0]
                    if request['kind']=='hide_image':
                        await self.hide_visual('requested')
                    elif (not self.session.private_mode and hasattr(self.providers,'prepare_visual') and
                          hasattr(self.providers,'visual_candidate')):
                        candidate=self.providers.visual_candidate(request)
                        if candidate is not None:
                            allowed,answer_public=revealable(plan,context,candidate)
                            if allowed:
                                self.invalidate_visual()
                                prepared=dict(session=self.session.session,turn=self.session.turn,
                                    revision=response_revision,topic=self.session.topic+1,token=uuid4().hex,
                                    epoch=self.epoch,output=self.session.output,ready=None,played=None,
                                    answer_asset=candidate.asset_id if answer_public else None)
                                self.prepared_visual=prepared
                                image_effect='image:'+prepared['token']
                                self.visual_task=asyncio.create_task(self.prepare_visual(prepared,request,operation))
                if answer_public:
                    state['secrets']={} # proposal only, committed by the final played ACK
                @asynccontextmanager
                async def planned():
                    async def items():
                        for sentence in plan['sentences']:
                            if len(plan['sentences']) > 1:
                                await self.review(operation, sentence)
                            yield sentence
                    yield items()
                manager = planned()
            else:
                manager = self.providers.answer(text, self.session.context())
            operation.ensure()
            async with self.owned_resource(operation, lambda: manager) as sentences:
                sentence_number = 0
                async for proposed in self.owned_items(operation, sentences):
                    sentence_number += 1
                    if not isinstance(proposed, str) or len(proposed) > 2048:
                        raise WireError('text capacity')
                    approved = self.policy.segment(proposed)
                    if not approved:
                        raise SafetyFault('content_blocked')
                    stage = 'synthesis'
                    async with self.owned_resource(operation, self.providers.synthesize, approved, 24000) as chunks:
                        # One-chunk lookahead marks the final chunk's public fact.
                        previous = None
                        async for chunk in self.owned_items(operation, chunks):
                            if not isinstance(chunk, bytes) or not chunk or len(chunk) % 2 or len(chunk) > 4800:
                                raise WireError('pcm capacity')
                            if previous is not None:
                                await self.audio(previous, '', epoch, operation=operation)
                            previous = chunk
                        if previous is None:
                            raise WireError('empty synthesis')
                        final_sentence=state is not None and sentence_number==len(plan['sentences'])
                        anchors=tuple(k for k,i in plan['anchors'].items() if i==sentence_number-1) if state is not None else ()
                        if final_sentence and answer_public: anchors=tuple(dict.fromkeys(anchors+('answer.current',)))
                        await self.audio(previous, approved, epoch,
                                         effect=image_effect if final_sentence else None,
                                         state=state if state is not None and sentence_number == len(plan['sentences']) else None,
                                         anchors=anchors, operation=operation)
            while self.session.pending:
                self.changed.clear()
                if epoch != self.epoch or not self.session._output_live():
                    raise WireError('revoked')
                await self.owned(operation, self.changed.wait)
            operation.ensure()
            self.session.deadline = 0
            await self.send('reply_end', head=self.session.head, public_facts=len(self.session.public))
        except StaleOperation:
            return
        except asyncio.CancelledError:
            raise
        except Exception as failure:
            if not operation.valid():
                return
            self.last_failure = dict(stage=stage, kind=type(failure).__name__)
            # Exception messages may contain provider content/credentials: never emit.
            self.session.interrupt()
            await self.commands()
            if self.session is not operation.session or epoch != self.epoch or self.session.turn != operation.turn:
                return
            if isinstance(failure, SafetyFault) or isinstance(failure, VoiceFault) and failure.code == 'safety':
                # Stop/revoke first. A newer input/connection cannot borrow this help notification.
                if self.revision != response_revision or self.closed or not self.session._live():
                    return
                # The local help replaces this failed response, not a new cloud retry.
                self.awaiting_input = False
                self.capture.clear()
                self.analysis = self.prepared = self.next_probe = None
                self.input_budget = ResponseBudget(self.session.clock)
                self.session.deadline = 0
                reason = failure.reason if isinstance(failure, SafetyFault) else 'content_blocked'
                await self.send('failure', code='safety', session=operation.session_id,
                                turn=operation.turn, revision=response_revision, local_help=local_help(reason))
            else:
                await self.send('failure', code=failure.code if isinstance(failure, VoiceFault) else 'timeout' if isinstance(failure, TimeoutError) else 'voice')
            if self.quarantined:
                await self.close_quarantined()
        finally:
            visual=self.prepared_visual
            if (visual is not None and visual['session']==operation.session_id and
                visual['turn']==operation.turn and visual['output']==operation.output and
                (owner.cancelling() or not operation.valid())):
                self.invalidate_visual()
            self.generation_scopes.pop(owner, None)
            text = ''

    async def audio(self, pcm, public, epoch, state=None, anchors=(), operation=None, effect=None):
        operation = operation or Operation(self, epoch)
        operation.ensure()
        while len(self.session.pending) >= 2 or self.suspended:
            self.changed.clear()
            if epoch != self.epoch or not self.session._output_live():
                raise WireError('revoked')
            await self.owned(operation, self.changed.wait)
        if epoch != self.epoch:
            raise WireError('revoked')
        await self.compact_memory(epoch, operation)
        if epoch != self.epoch or not self.session._output_live():
            raise WireError('revoked')
        name, start = uuid4().hex, self.session.sent_end
        end = start + len(pcm)//2
        if not self.session.send(replace(self.tts_identity, sequence=self.send_sequence),
                                 name=name, public=public, end=end, approved=True, effective=True, state=state, anchors=anchors, effect=effect):
            raise WireError('send rejected')
        self.send_sequence += 1
        await self.send('audio', player=self.session.player, stream=self.session.stream,
                        segment=name, start=start, end=end, pcm=base64.b64encode(pcm).decode())

    async def monitor(self):
        while not self.closed:
            await asyncio.sleep(.1)
            if self.quarantined:
                await self.send('failure', code='voice')
                await self.close_quarantined()
                return
            if self.awaiting_input and self.input_budget.thinking_at is None:
                try:
                    self.input_budget.remaining()
                except (TimeoutError, ValueError):
                    self.session.interrupt()
                    await self.commands()
                    await self.cancel_generation()
                    await self.cancel_recognition()
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
            self.invalidate_visual()
            for task in (monitor, receiver, self.recognition):
                if task is not None:
                    task.cancel()
            tasks = {t for t in (monitor, receiver, self.recognition) if t is not None} | self.retired_tasks
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
