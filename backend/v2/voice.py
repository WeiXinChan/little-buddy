"""V2 in-memory full-duplex session adapter. No supplier or deployment defaults.

Providers are injected AFTER their privacy gate; the local fixture uses this exact
adapter. All Session mutations occur on the websocket event loop, never a worker.
"""
from backend.v2.diagnostics import contract_code,contract_detail
from backend.v2 import failure_observer
import asyncio
import base64
import json
import time
import sys
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from copy import deepcopy
from uuid import uuid4

from backend.v2.session import Identity, Session
from backend.v2.budget import ResponseBudget
from backend.v2.safety import SafetyFault, local_help
from backend.v2.review import ReviewDecision,QualityFault
from backend.v2.images import revealable
from backend.v2.dynamic_images import ImageScope, ImageFailure
from backend.v2.image_descriptions import ExplicitImageRequest
from backend.v2.image_wire import PublicImage, CHUNK_BYTES
from backend.v2.protocol import CONTRACT
from backend.v2 import timing as stage_timing


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
        self.input_anchor = self.budget.anchor
        self.output = None
        self.private_mode = self.session.private_mode
        self.cancelled = False

    def valid(self):
        p, s = self.peer, self.session
        return (not self.cancelled and not p.closed and not p.quarantined and not s.management_paused
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
    if not isinstance(raw,str) or len(raw.encode())>16000:raise WireError('size')
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
               'ack': {'identity', 'player', 'stream', 'segment', 'head'}, 'end': set(), 'scope':set(),
               'management_pause':{'session','turn','revision'},
               'management_resume':{'session','turn','revision','pause'}}
    if (not isinstance(event, dict) or event.get('v') != 2 or type(event.get('v')) is not int
            or event.get('type') not in schemas
            or (set(event) - ({'speech', 'age_ms'} if event['type'] == 'input' else {'age_ms'} if event['type'] == 'wake_solo' else {'features','image_contract'} if event['type'] == 'bind' else set())) != schemas[event['type']] | {'v', 'type', 'epoch', 'seq'}
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
        self.recognition_handoff = None
        self.next_probe = None
        self.prepared = None
        self.revision = 0
        self.analysis = None
        self.input_resolution = None
        self.prompted_revision = None
        self.quarantined = False
        self.suspended = False
        self.changed = asyncio.Event()
        self.ack_identity = None
        self.ack_sequence = 0
        self.send_sequence = 0
        self.closed = False
        self.images_enabled = False
        self.dynamic_enabled = False
        self.visual_cache = None
        self.display_scope = None
        self.prepared_visual = None
        self.visual_task = None
        self.recognition_scopes = {}
        self.generation_scopes = {}
        self.retired_tasks = set()
        self.management_receipt=None
        self.management_ready=False
        self.management_scope=None
        self.waiting_wake=False
        self.last_volume_scope=None
        self.settling_stop=None
        self.expiry_notice_scope=None

    @asynccontextmanager
    async def resource(self, manager):
        # Release failures and bounded cancellation are resource health failures,
        # never merely another retryable provider response.
        async with asyncio.timeout(4):
            value = await manager.__aenter__()
        try:
            yield value
        finally:
            close_started=asyncio.get_running_loop().time()
            exit_task = asyncio.create_task(manager.__aexit__(*sys.exc_info()))
            self.track_retired(exit_task)
            try:
                done, _ = await asyncio.wait({exit_task}, timeout=.5)
            except asyncio.CancelledError:
                # Cancellation can race a successful close. Confirm the same
                # close task within the existing bound before classifying the
                # connection unhealthy; never turn cancellation into reuse of
                # an unconfirmed resource.
                try:
                    remaining=max(0.,.5-(asyncio.get_running_loop().time()-close_started))
                    done,_=await asyncio.wait({exit_task},timeout=remaining)
                    confirmed=bool(done) and not exit_task.cancelled() and exit_task.exception() is None
                except asyncio.CancelledError:
                    confirmed=False
                if not confirmed:
                    self.quarantined=True
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

    async def read_request(self, operation, kind, *args, allow_plan_repair=True):
        """One transient retry for proposal-only reads, never media or safety.

        Only the explicit endpoint/plan/facts call sites use this port. No
        state/output is committed by those provider contracts. The original
        expression budget owns the retry across turn/player reconstruction.
        """
        if kind not in {'endpoint', 'plan', 'facts'}:
            raise ValueError('read request stage')
        async def timed(function,*values,**options):
            stage_timing.mark(kind+'_start',self,operation)
            try:result=await self.owned(operation,function,*values,**options)
            except BaseException:
                stage_timing.mark(kind+'_end',self,operation,outcome='failed');raise
            stage_timing.mark(kind+'_end',self,operation)
            return result
        function = getattr(self.providers, kind)
        revision = self.revision
        snapshot=deepcopy(args) if kind=='plan' else args
        initial_args=deepcopy(snapshot) if kind=='plan' else args
        try:
            result = await timed(function, *initial_args)
            if revision != self.revision:
                raise StaleOperation()
            return result
        except Exception as failure:
            operation.ensure()
            if revision != self.revision:
                raise StaleOperation()
            from backend.v2.companion import ModelError
            repair_limit=getattr(failure,'repair_sentence_limit',None)
            sentence_repair=(type(repair_limit) is int and 1<=repair_limit<=4 and contract_code(failure)=='plan_sentence_limit' and callable(getattr(self.providers,'repair_plan',None)))
            format_repair=(contract_code(failure)=='plan_anchors' and contract_detail(failure) in ('anchor_index_type','anchor_index_range') and callable(getattr(self.providers,'repair_plan_format',None)))
            repair=((sentence_repair or format_repair) and isinstance(failure,ModelError) and allow_plan_repair and kind=='plan' and
                    len(snapshot)==2 and isinstance(snapshot[1],dict) and not self.session.private_mode and not snapshot[1].get('private') and
                    self.prepared is None and not self.waiting_wake and operation.budget is self.input_budget)
            transient=isinstance(failure,VoiceFault) and failure.code in {'network','timeout'}
            if not repair and not transient:raise
            budget = operation.budget
            if (budget.read_retry_revision == revision or
                    (kind != 'endpoint' and (self.session.response_confirmed or self.session.pending))):
                raise
            remaining = budget.remaining()
            budget.read_retry_revision = revision  # reserve before the next await
            async with asyncio.timeout(remaining):
                retry_function=(self.providers.repair_plan_format if format_repair else self.providers.repair_plan) if repair else function
                retry_args=deepcopy(snapshot) if kind=='plan' else args
                if repair and format_repair:result=await timed(retry_function,*retry_args,code='plan_anchors',detail=contract_detail(failure))
                elif repair:result=await timed(retry_function,*retry_args,sentence_limit=repair_limit)
                else:result=await timed(retry_function,*retry_args)
            if revision != self.revision:
                raise StaleOperation()
            # An adapter swallowing cancellation or a changed clock cannot
            # publish a result outside the original first-response budget.
            budget.remaining()
            return result

    @asynccontextmanager
    async def owned_resource(self, operation, factory, *args):
        operation.ensure()
        with stage_timing.provider_marks(self,operation):
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

    def retire_recognition_for_advance(self):
        old=self.recognition
        if old is None or old.done() or self.recognition_handoff is not None:return
        scope=self.recognition_scopes.get(old)
        if scope is not None:scope.cancelled=True
        authority=(self.session,self.session.session,self.session.connection,self.epoch,self.session.private_mode)
        deadline=asyncio.get_running_loop().time()+.5
        old.cancel()
        self.recognition_handoff=asyncio.create_task(self.finish_recognition_handoff(old,authority,deadline))
        self.track_retired(self.recognition_handoff)

    async def finish_recognition_handoff(self,old,authority,deadline):
        owner=asyncio.current_task()
        try:
            done,_=await asyncio.wait({old},timeout=max(0,deadline-asyncio.get_running_loop().time()))
            if not done or not old.cancelled() and old.exception() is not None:
                self.quarantined=True;self.track_retired(old)
                if self.next_probe is not None and self.next_probe[2] is old:self.next_probe=None
                return
            if self.quarantined or self.recognition_handoff is not owner or self.recognition is not old:return
            pending=self.next_probe;self.next_probe=None;self.recognition=None
            current=(self.session,self.session.session,self.session.connection,self.epoch,self.session.private_mode)
            if current!=authority or pending is None or pending[2] is not old:return
            data,following,_=pending
            if following.valid() and following.private_mode==self.session.private_mode:
                self.recognition=asyncio.create_task(self._analyze(data,following))
        except asyncio.CancelledError:
            if not old.done():
                self.track_retired(old)
                if self.recognition_handoff is owner:
                    self.quarantined=True
                    if self.next_probe is not None and self.next_probe[2] is old:self.next_probe=None
            raise
        finally:
            if self.recognition_handoff is owner:self.recognition_handoff=None

    async def cancel_recognition(self):
        task=self.recognition
        handoff,self.recognition_handoff=self.recognition_handoff,None
        self.next_probe=None
        tasks={t for t in (task,handoff) if t is not None and not t.done()}
        if not tasks:return
        scope=self.recognition_scopes.get(task)
        if scope is not None:scope.cancelled=True
        for t in tasks:t.cancel()
        try:done,pending=await asyncio.wait(tasks,timeout=.5)
        except asyncio.CancelledError:
            self.quarantined=True
            for t in tasks:
                if not t.done():self.track_retired(t)
            raise
        if pending:
            self.quarantined=True
            for t in pending:self.track_retired(t)
        for t in done:
            if not t.cancelled() and t.exception() is not None:self.quarantined=True

    async def close_quarantined(self):
        task = asyncio.create_task(self.socket.close(1011, 'resource unavailable'))
        done, _ = await asyncio.wait({task}, timeout=.5)
        if not done:
            task.cancel()
            self.track_retired(task)
        elif not task.cancelled():
            task.exception()

    async def send(self, kind, **fields):
        if kind=='scope':fields['protocol_contract']=CONTRACT
        if kind in {'bound', 'open','scope','management_state'}:
            # Establish scope on normal authenticated control frames, never learn it from a fault.
            fields.setdefault('session', self.session.session)
            fields.setdefault('turn', self.session.turn)
            fields.setdefault('revision', self.revision)
        diagnostic=Operation(self,self.epoch,self.revision) if stage_timing.enabled() else None
        async with asyncio.timeout(2):
            await self.socket.send(json.dumps(dict(v=2, type=kind, epoch=self.epoch, **fields)))
        stage={'endpoint':'endpoint_sent','decision':'decision_sent','open':'open_sent','bound':'bound_sent','audio':'first_audio_sent','reply_end':'reply_end','session_end':'session_end','failure':'failure'}.get(kind)
        if stage:stage_timing.mark(stage,self,diagnostic)

    async def commands(self):
        session, epoch, turn = self.session, self.epoch, self.session.turn
        for command in session.drain_commands():
            if self.session is not session or self.epoch != epoch or session.turn != turn:
                break
            if command[0] == 'mute_flush':
                self.invalidate_visual(keep_cache=True)
                await self.send('revoke')
            elif command[0] == 'reveal':
                if command[1].startswith('image:'):
                    prepared=self.prepared_visual
                    if (prepared is not None and command[1]=='image:'+prepared['token'] and
                        self.visual_live(prepared) and command[2]==prepared['topic'] and len(command)==5):
                        prepared['played']=(command[3],command[4])
                        if prepared.get('dynamic') or prepared.get('control'):
                            if prepared.get('control'):
                                cache=prepared['cache']
                                if (cache is not self.visual_cache or cache.topic!=prepared['topic']-1 or
                                    cache.remaining()<=0 or cache.session!=self.session.session or
                                    cache.connection!=self.session.connection or self.session.secrets):continue
                                cache.topic=prepared['topic']
                            if self.visual_task is None:
                                self.visual_task=asyncio.create_task(self.prepare_visual(prepared,prepared['request'],prepared['operation']))
                        else:
                            await self.reveal_visual(prepared)
                else:
                    await self.send('reveal', effect=command[1], topic=command[2])
        self.changed.set()

    def visual_live(self, value):
        return (self.images_enabled and not self.closed and not self.quarantined and not self.session.management_paused and
                not self.session.private_mode and self.session._output_live() and value['session']==self.session.session and
                value['turn']==self.session.turn and value['revision']==self.revision and
                value['epoch']==self.epoch and value['output']==self.session.output and
                value.get('connection',self.session.connection)==self.session.connection and
                value.get('player',self.session.player)==self.session.player and value.get('stream',self.session.stream)==self.session.stream)

    def cache_live(self,cache):
        return (cache is not None and cache.remaining()>0 and self.session._live() and not self.closed and
                not self.quarantined and not self.session.management_paused and not self.session.private_mode and
                not self.session.secrets and cache.session==self.session.session and
                cache.connection==self.session.connection and cache.topic==self.session.topic)

    def invalidate_visual(self, *, keep_cache=False):
        prepared,self.prepared_visual=self.prepared_visual,None
        if prepared is not None and prepared.get('scope') is not None:
            self.providers.cancel_generated_image(prepared['scope'])
        task,self.visual_task=self.visual_task,None
        if task is not None and not task.done():
            task.cancel();self.track_retired(task)
        self.display_scope=None
        if self.visual_cache is not None:
            self.visual_cache.visible_until=0.
            if not keep_cache or not self.cache_live(self.visual_cache):
                self.visual_cache.release();self.visual_cache=None

    def image_current(self,prepared):
        return (self.prepared_visual is prepared and self.visual_live(prepared) and
                prepared['topic']==self.session.topic and not self.session.secrets)

    async def send_visual(self,prepared,kind,**fields):
        if not self.image_current(prepared):raise ImageFailure('stale')
        cache=prepared.get('cache')
        if cache is not None and not self.cache_live(cache):raise ImageFailure('stale')
        scope={k:prepared[k] for k in ('session','turn','revision','topic','token')}
        if len(json.dumps(dict(v=2,type=kind,epoch=self.epoch,**scope,**fields)).encode())>16000:raise ImageFailure('payload')
        await self.send(kind,**scope,**fields)
        if not self.image_current(prepared):raise ImageFailure('stale')
        if cache is not None and not self.cache_live(cache):raise ImageFailure('stale')

    async def prepare_visual(self, prepared, request, operation):
        owner=asyncio.current_task();image=None;cache=None;published=False
        try:
            if prepared.get('control'):
                cache=prepared['cache']
                if (not self.image_current(prepared) or cache is not self.visual_cache or
                    not self.cache_live(cache)):return
            elif prepared.get('dynamic'):
                if not self.image_current(prepared):return
                scope=ImageScope(prepared['session'],prepared['turn'],prepared['epoch'],prepared['revision'],prepared['topic'])
                prepared['scope']=scope
                image=await self.providers.prepare_dynamic_visual(request,scope,
                    lambda candidate: candidate==scope and self.image_current(prepared))
                if not self.image_current(prepared):return
                cache=PublicImage.generated(image,scope,request['asset_id'],self.session.connection)
                image.release();image=None
                prepared['cache']=cache
            else:
                image=await self.owned(operation,self.providers.prepare_visual,request)
                if self.prepared_visual is not prepared or not self.visual_live(prepared) or image is None:return
                if prepared['answer_asset'] is not None and image.asset_id!=prepared['answer_asset']:return
                prepared['ready']=image.payload()
                fields={k:prepared[k] for k in ('session','turn','revision','topic','token')}
                if not self.dynamic_enabled:await self.send('image_ready',**fields,**prepared['ready'])
                if self.prepared_visual is prepared and self.visual_live(prepared):await self.reveal_visual(prepared)
                return
            if not self.cache_live(cache):return
            if self.visual_cache is not None and self.visual_cache is not cache:self.visual_cache.release()
            self.visual_cache=cache
            prepared['ready']=cache.metadata
            async with asyncio.timeout(2):
                if cache.png and prepared.get('control')!='hide':
                    await self.send_visual(prepared,'image_begin',**cache.fields(),bytes=len(cache.png),
                        chunks=(len(cache.png)+CHUNK_BYTES-1)//CHUNK_BYTES,chunk_bytes=CHUNK_BYTES,encoding='base64')
                    for packet in cache.packets():await self.send_visual(prepared,'image_chunk',**cache.fields(),**packet)
                if prepared.get('control')!='hide':await self.send_visual(prepared,'image_ready',**cache.fields())
                await self.reveal_visual(prepared)
                published=self.prepared_visual is not prepared
        except (StaleOperation,asyncio.CancelledError):
            return
        except Exception:
            if image is not None and prepared.get('dynamic'):image.release();image=None
            if cache is not None:
                cache.release()
                if self.visual_cache is cache:self.visual_cache=None
                prepared.pop('cache',None)
            if self.image_current(prepared):
                try:await self.send_visual(prepared,'image_status',image_v=2,state='unavailable',reason='image_unavailable')
                except Exception:pass
                await self.image_failure_speech(prepared,request,operation)
            if self.prepared_visual is prepared:self.prepared_visual=None
        finally:
            if image is not None and prepared.get('dynamic'):image.release()
            if cache is not None and (not published or self.visual_cache is not cache):
                cache.release()
                if self.visual_cache is cache:self.visual_cache=None
            if self.prepared_visual is prepared and prepared.get('dynamic'):self.prepared_visual=None
            if self.visual_task is owner:self.visual_task=None

    async def image_failure_speech(self,prepared,request,operation):
        # Only local PLAN provenance marks an explicit request. Decoration has no
        # audible side effect. Consume before IO; never retry this fixed message.
        if not isinstance(request,ExplicitImageRequest) or prepared.get('failure_spoken'):return
        deadline=operation.budget.deadline
        if deadline is None:deadline=operation.session.deadline
        def current():
            return (self.image_current(prepared) and operation.valid() and not self.suspended and
                    not self.waiting_wake and deadline and operation.session.clock()<deadline)
        if not current():return
        prepared['failure_spoken']=True
        scoped=Operation(self,prepared['epoch'],prepared['revision'])
        scoped.output=prepared['output'];scoped.budget=operation.budget
        text='这张图暂时没生成好，我们先接着聊。'
        def ensure():
            scoped.ensure()
            if not current():raise StaleOperation()
        audio_started=False;completed=False
        try:
            async with asyncio.timeout(max(0.,deadline-operation.session.clock())):
                ensure()
                async with self.owned_resource(scoped,self.providers.synthesize,text,24000) as chunks:
                    previous=None
                    async for pcm in self.owned_items(scoped,chunks):
                        ensure()
                        if not isinstance(pcm,bytes) or not pcm or len(pcm)%2 or len(pcm)>4800:
                            raise WireError('pcm capacity')
                        if previous is not None:
                            audio_started=True
                            await self.audio(previous,'',prepared['epoch'],operation=scoped);ensure()
                        previous=pcm
                    ensure()
                    if previous is None:raise WireError('empty synthesis')
                    audio_started=True
                    await self.audio(previous,text,prepared['epoch'],operation=scoped);ensure()
                while self.session.pending:
                    self.changed.clear();ensure()
                    await self.owned(scoped,self.changed.wait);ensure()
                ensure()
                await self.owned(scoped,self.send,'reply_end',head=self.session.head,public_facts=len(self.session.public))
                ensure();completed=True
        except (StaleOperation,asyncio.CancelledError):return
        except Exception:return # failed fixed help cannot trigger another synthesis or provider retry
        finally:
            # Revoke only this original playback if help was queued but never
            # completely ACKed. A later player/turn/output is never touched.
            if (audio_started and not completed and self.session is operation.session and
                self.session.connection==operation.connection and self.session.turn==prepared['turn'] and
                self.session.output==prepared['output'] and self.session.player==prepared['player'] and
                self.session.stream==prepared['stream']):
                if self.visual_task is asyncio.current_task():self.visual_task=None
                self.session.interrupt()
                await self.commands()

    async def reveal_visual(self, prepared):
        if (self.prepared_visual is not prepared or not self.visual_live(prepared) or
            prepared['ready'] is None or prepared['played'] is None or prepared['topic']!=self.session.topic):return
        fields={k:prepared[k] for k in ('session','turn','revision','topic','token')}
        if self.dynamic_enabled:
            cache=prepared.get('cache')
            if cache is None:
                if self.session.secrets:return
                cache=PublicImage(dict(prepared['ready'],image_id=prepared['token']),session=self.session.session,
                    connection=self.session.connection,topic=self.session.topic,seconds=15.)
                if self.visual_cache is not None:self.visual_cache.release()
                self.visual_cache=cache;prepared['cache']=cache
                await self.send_visual(prepared,'image_ready',**cache.fields())
            if not self.cache_live(cache):return
            action=prepared.get('control','display')
            if action=='hide':cache.visible_until=0.;duration=0
            else:duration=cache.display(action,prepared['display_seconds'])
            await self.send_visual(prepared,'image_display',**cache.fields(),action=action,duration_ms=duration,
                player=self.session.player,stream=self.session.stream,segment=prepared['played'][0],end=prepared['played'][1])
            self.display_scope=None if action=='hide' else dict(fields,epoch=self.epoch)
        else:
            await self.send('reveal',effect='image:'+prepared['token'],**fields,
                asset_id=prepared['ready']['asset_id'],sha256=prepared['ready']['sha256'],
                player=self.session.player,stream=self.session.stream,
                segment=prepared['played'][0],end=prepared['played'][1])
        if self.prepared_visual is prepared:self.prepared_visual=None

    async def hide_visual(self, reason):
        self.invalidate_visual(keep_cache=reason in {'input_changed','requested'})
        if self.images_enabled:
            await self.send('hide', session=self.session.session,turn=self.session.turn,
                            revision=self.revision,topic=self.session.topic,reason=reason)

    async def poll_visual(self):
        cache=self.visual_cache
        if cache is None:return
        if not self.cache_live(cache) or (cache.visible_until and asyncio.get_running_loop().time()>=cache.visible_until):
            display=self.display_scope;self.display_scope=None;cache.visible_until=0.
            if not self.cache_live(cache):
                cache.release()
                if self.visual_cache is cache:self.visual_cache=None
            if display is not None:
                await self.send('image_display',**{k:v for k,v in display.items() if k!='epoch'},
                    **cache.fields(),action='hide',duration_ms=0,reason='expired',eyes=True)

    async def cancel_generation(self):
        task, self.generation = self.generation, None
        await self.cancel_generation_task(task)

    async def cancel_generation_task(self,task):
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
        if self.closed:return
        if self.quarantined and event['type'] != 'end':
            raise WireError('quarantined')
        kind, epoch, seq = event['type'], event['epoch'], event['seq']
        if epoch < self.epoch:
            return  # Revoked audio, ASR and playback callbacks have no effects.
        if kind in {'management_pause','management_resume'}:
            if (not isinstance(event['session'],str) or type(event['turn']) is not int or
                type(event['revision']) is not int):raise WireError('management scope')
            if (event['session']!=self.session.session or event['turn']!=self.session.turn or
                event['revision']!=self.revision+1):return
            if not self.session._live():
                self.management_receipt=None;self.management_ready=False;self.management_scope=None
                await self.send('management_state',management_v=1,state='expired',pause=None)
                return
            if kind=='management_pause' and self.session.management_paused:return
            if kind=='management_resume' and (not self.session.management_paused or not self.management_ready or
                not isinstance(event['pause'],str) or event['pause']!=self.management_receipt or
                self.management_scope!=(self.session,self.session.connection,self.session.session,self.session.turn,
                    self.session.output,self.epoch,self.revision)):return
            if epoch!=self.epoch+1 or seq!=0:raise WireError('management epoch')
        # Management/wake-only barriers run before media decoding. Same-epoch
        # discarded frames still consume their strict sequence number.
        # Queued old microphone data cannot be retained or dispatched upstream.
        allowed={'heartbeat','scope','end','management_pause','management_resume'}
        blocked=(self.session.management_paused and kind not in allowed or
                 self.waiting_wake and kind not in allowed|{'wake','wake_solo'})
        if blocked and epoch>self.epoch:return
        if epoch > self.epoch:
            if epoch != self.epoch + 1 or kind not in {'stop','management_pause','management_resume'} or seq != 0:
                raise WireError('epoch')
            self.epoch, self.sequence = epoch, -1
        if seq != self.sequence + 1:
            raise WireError('sequence')
        self.sequence = seq
        if blocked:return
        stage={'probe':'probe_received','seal':'seal_received','stop':'stop_received','bind':'bind_received','ack':'ack_received'}.get(kind)
        if stage:stage_timing.mark(stage,self)
        if kind=='scope':
            live=self.session._live()
            state='expired' if not live else 'paused' if self.session.management_paused else 'waiting_wake' if self.waiting_wake else 'active'
            await self.send('scope',management_v=1,state=state)
        elif kind=='management_pause':
            self.revision=event['revision']
            self.session.pause_management()
            self.management_receipt=uuid4().hex;self.management_ready=False
            self.management_scope=(self.session,self.session.connection,self.session.session,self.session.turn,
                                   self.session.output,self.epoch,self.revision)
            self.waiting_wake=False;self.suspended=True
            self.capture.clear();self.analysis=self.next_probe=self.prepared=None
            self.awaiting_input=False;self.prompted_revision=None
            self.input_budget=ResponseBudget(self.session.clock)
            self.ack_identity=None
            self.invalidate_visual()
            await self.cancel_recognition()
            await self.cancel_generation()
            await self.commands()
            if self.quarantined:raise WireError('management resource unavailable')
            if not self.session._live():
                self.management_receipt=None
                await self.send('management_state',management_v=1,state='expired',pause=None)
                return
            self.management_ready=True
            await self.send('management_state',management_v=1,state='paused',pause=self.management_receipt)
        elif kind=='management_resume':
            self.management_receipt=None;self.management_ready=False;self.management_scope=None
            self.revision=event['revision']
            if not self.session.resume_management():return
            self.waiting_wake=True;self.suspended=False
            self.capture.clear();self.analysis=self.next_probe=self.prepared=None
            self.awaiting_input=False;self.ack_identity=None
            self.input_budget=ResponseBudget(self.session.clock)
            await self.send('management_state',management_v=1,state='waiting_wake',pause=None)
        elif kind == 'heartbeat':
            self.session.heartbeat()
        elif kind == 'stop':
            session=self.session;old_generation=self.generation;prepared=self.prepared
            self.session.interrupt()
            self.capture.clear()
            self.suspended=False
            scope=(session,self.epoch,self.revision,session.connection,session.turn,session.output)
            timing=(session.deadline,session.progress_deadline,session.response_confirmed,session.response_expired)
            budget=self.input_budget;budget_deadline=budget.deadline
            token=dict(scope=scope,generation=old_generation,prepared=prepared,budget=budget,
                       budget_deadline=budget_deadline,timing=timing)
            self.settling_stop=token
            try:
                await self.commands()
                if self.generation is old_generation:await self.cancel_generation()
                else:await self.cancel_generation_task(old_generation)
                current=(self.session,self.epoch,self.revision,self.session.connection,self.session.turn,self.session.output)
                current_timing=(session.deadline,session.progress_deadline,session.response_confirmed,session.response_expired)
                if (current!=scope or current_timing!=timing or self.generation is not None or
                    self.closed or self.quarantined or any(not t.done() for t in self.retired_tasks) or not session._live()):return
                # Retire only fields still owned by the captured revoked reply.
                # A replacement prepared/input budget is preserved, not consumed.
                replaced=(self.prepared is not prepared or self.input_budget is not budget or budget.deadline!=budget_deadline)
                if replaced:
                    session.deadline=session.progress_deadline=0
                    session.response_confirmed=session.response_expired=False
                    return
                self.prepared=None
                if prepared is not None and event['intent']==prepared[2]:
                    text,deadline,_,revision=prepared
                    if revision!=self.revision:return
                    if session.clock()>=deadline:raise WireError('response budget exhausted')
                    session.begin_turn();session.deadline=deadline
                    self.awaiting_input=False
                    await self.commands();await self.send('open',revision=self.revision)
                    self.generation=asyncio.create_task(self.respond(text,self.epoch))
                else:
                    # Confirmed stopped old reply, not a session/lease renewal.
                    session.deadline=session.progress_deadline=0
                    session.response_confirmed=session.response_expired=False
                    # Follow only the client's adjacent stop barrier for this
                    # already-resolved input; a new revision still admits speech.
                    key=self.input_resolution_key()
                    prior=self.input_resolution
                    if (not event['intent'] and prior is not None and
                        prior[:3]==key[:3] and prior[4]==key[4] and prior[3]+1==key[3] and
                        budget.anchor is None):self.input_resolution=key
            finally:
                if self.settling_stop is token:self.settling_stop=None
        elif kind == 'end':
            self.management_receipt=None;self.management_ready=False;self.management_scope=None;self.waiting_wake=False
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
            if self.input_resolution==self.input_resolution_key():return
            if speech:
                self.input_budget.speech(age)
                self.awaiting_input = True
            self.capture.extend(data)
        elif kind == 'wake':
            self.waiting_wake=False
            self.session.valid_interaction()
        elif kind == 'wake_solo':
            self.waiting_wake=False
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
            self.next_probe=None
            self.retire_recognition_for_advance()
            self.suspended = True
            await self.hide_visual('input_changed')
            self.analysis = self.prepared = None
            self.session.valid_interaction()
            # Snapshot analysis can finish, but its old version cannot take effect.
        elif kind == 'probe':
            if self.input_resolution==self.input_resolution_key():return
            if event['revision'] != self.revision or not self.capture:
                return
            self.input_budget.resume()
            self.input_budget.remaining()
            if self.recognition_handoff is not None or self.recognition is not None and not self.recognition.done():
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
            if not isinstance(features,list) or len(features)>1 or any(x not in {'images_v1','images_v2'} for x in features):
                raise WireError('features')
            dynamic='images_v2' in features
            if dynamic and event.get('image_contract')!=CONTRACT:raise WireError('image contract')
            self.dynamic_enabled=dynamic;self.images_enabled=bool(features)
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
            diagnostic=Operation(self,self.epoch,self.revision) if stage_timing.enabled() else None
            before_head=self.session.head;before_effective=self.session.response_confirmed
            accepted=self.session.ack(identity, player=event['player'], stream=event['stream'],
                             segment=event['segment'], head=event['head'])
            if accepted and self.session.head>before_head:stage_timing.mark('ack_progress',self,diagnostic,count=self.session.head-before_head)
            if accepted and not before_effective and self.session.response_confirmed:stage_timing.mark('effective_ack',self,diagnostic)
            await self.commands()

    def input_resolution_key(self):
        return (self.session.session,self.session.connection,self.session.turn,self.epoch,self.revision)

    async def finish_input_analysis(self,operation,*,outcome=None,failure=None):
        def ensure_current():
            operation.ensure()
            if (operation.private_mode!=operation.session.private_mode or
                self.input_budget is not operation.budget or self.input_budget.anchor!=operation.input_anchor):
                raise StaleOperation()
            session=operation.session
            if session.response_expired:raise StaleOperation()
            if session.deadline and (session.player is not None or session.pending):
                if not session._output_live():raise StaleOperation()
        ensure_current()
        key=self.input_resolution_key()
        if self.input_resolution==key:return
        # An already-expired expression remains a timeout with its original
        # boundary. Do not consume it through the finite unknown resolution.
        if failure is not None and operation.budget.deadline is not None and operation.session.clock()>=operation.budget.deadline:
            await self.owned(operation,self.send,'failure',code='timeout',revision=operation.revision)
            return
        if failure is None:
            if outcome not in {'asr_empty','semantic_unknown'}:raise ValueError('analysis outcome')
            operation.budget.remaining()
        generation=self.generation
        close_started=asyncio.get_running_loop().time()
        try:await self.cancel_generation_task(generation)
        except asyncio.CancelledError:
            # A superseding input may cancel this analysis while old output exits.
            # Observe that same task within the original .5s, never grant another .5s.
            if generation is not None and not generation.done():
                try:
                    done,_=await asyncio.wait({generation},timeout=max(0,.5-(asyncio.get_running_loop().time()-close_started)))
                except asyncio.CancelledError:done=set()
                if not done:
                    self.quarantined=True;self.track_retired(generation)
            raise
        ensure_current()
        if self.generation is not generation:raise StaleOperation()
        if failure is None:operation.budget.remaining()
        self.generation=None
        self.session.interrupt()
        self.session.deadline=self.session.progress_deadline=0
        self.session.response_confirmed=self.session.response_expired=False
        self.input_resolution=key
        self.awaiting_input=False
        self.capture.clear();self.analysis=self.prepared=self.next_probe=None
        self.input_budget=ResponseBudget(self.session.clock) # inactive, NOT a new 15s grant
        inactive_budget=self.input_budget
        def ensure_resolved():
            operation.ensure()
            if (operation.private_mode!=operation.session.private_mode or
                self.input_budget is not inactive_budget or inactive_budget.anchor is not None):raise StaleOperation()
        await self.commands()
        ensure_resolved()
        fields=dict(session=operation.session_id,turn=operation.turn,revision=operation.revision)
        await self.owned(operation,self.send,'scope',management_v=1,state='active',**fields)
        ensure_resolved()
        if failure is None:
            await self.owned(operation,self.send,'decision',meaning='unknown',intent='',revision=operation.revision)
        else:
            from backend.dashscope import SpeechTaskError
            if isinstance(failure,(VoiceFault,SafetyFault)):code=failure.code
            elif isinstance(failure,TimeoutError):code='timeout'
            elif isinstance(failure,SpeechTaskError) and failure.code in {'insufficient_quota','AllocationQuota.FreeTierOnly'}:code='quota'
            elif isinstance(failure,OSError):code='network'
            else:code='voice'
            if isinstance(failure,SafetyFault):fields['local_help']=local_help(failure.reason)
            await self.owned(operation,self.send,'failure',code=code,**fields)

    def analyze(self, pcm, epoch, revision):
        # Bind on invocation, before create_task can be delayed until a handoff.
        return self._analyze(pcm, Operation(self, epoch, revision))

    async def _analyze(self, pcm, operation):
        owner = asyncio.current_task()
        self.recognition_scopes[owner] = operation
        try:
            operation.ensure()
            if operation.private_mode!=operation.session.private_mode:raise StaleOperation()
            async with asyncio.timeout(operation.budget.remaining()):
                stage_timing.mark('asr_open',self,operation)
                async with self.owned_resource(operation, self.providers.recognize, 16000) as recognizer:
                    stage_timing.mark('asr_ready',self,operation)
                    for offset in range(0, len(pcm), 6400):
                        await self.owned(operation, recognizer.write, pcm[offset:offset+6400])
                    text = await self.owned(operation, recognizer.finish)
                    stage_timing.mark('asr_final',self,operation)
                stage_timing.mark('asr_released',self,operation)
                operation.ensure()
                if isinstance(text,str) and not text.strip():
                    await self.finish_input_analysis(operation,outcome='asr_empty')
                    return
                text = self.policy.input(text)
                operation.ensure()
                if operation.private_mode!=operation.session.private_mode:raise StaleOperation()
                # Only this operation's authorised session may supply context.
                context = operation.session.context()
                result = await self.read_request(operation, 'endpoint', text, context)
                if (not isinstance(result, dict) or set(result) != {'completion', 'meaning'}
                        or result['completion'] not in {'complete', 'incomplete', 'thinking'}
                        or result['meaning'] not in {'new_turn', 'stop', 'noise', 'backchannel', 'thinking', 'unknown','management','volume_up','volume_down'}):
                    raise WireError('endpoint schema')
                operation.ensure()
                operation.budget.remaining()
                if result['completion'] == 'thinking':
                    operation.budget.pause_thinking()
                if operation.private_mode!=operation.session.private_mode:raise StaleOperation()
                self.analysis = (operation.revision, text, result['completion'], result['meaning'])
                await self.owned(operation, self.send, 'endpoint',
                                 revision=operation.revision, completion=result['completion'])
        except StaleOperation:
            return
        except asyncio.CancelledError:
            stage_timing.mark('cancel',self,operation,outcome='cancelled')
            raise
        except Exception as failure:
            if operation.valid() and operation.private_mode==operation.session.private_mode:
                try:await self.finish_input_analysis(operation,failure=failure)
                except StaleOperation:return
        finally:
            pcm = b''
            self.recognition_scopes.pop(owner, None)
            # An old finally must not consume a newer owner's pending probe.
            pending = self.next_probe
            if self.recognition_handoff is None and self.recognition is owner and pending is not None and pending[2] is owner:
                self.next_probe = None
                data, following, _ = pending
                if following.valid() and not operation.cancelled and not owner.cancelling():
                    self.recognition = asyncio.create_task(self._analyze(data, following))

    async def decision(self, text, meaning, revision, deadline):
        if meaning=='unknown':
            await self.finish_input_analysis(Operation(self,self.epoch,revision),outcome='semantic_unknown')
            return
        if meaning in {'volume_up','volume_down'}:
            session,epoch,turn,connection=self.session,self.epoch,self.session.turn,self.session.connection
            key=(session.session,connection,turn,epoch,revision)
            def current():
                return (self.session is session and session._live() and not session.management_paused and
                        not self.closed and not self.quarantined and not self.waiting_wake and
                        self.epoch==epoch and self.revision==revision and session.turn==turn and
                        session.connection==connection and session.clock()<deadline)
            if not current() or self.last_volume_scope==key:return
            self.last_volume_scope=key # consume before IO; failed writes never auto-repeat an increase
            self.awaiting_input=False;self.capture.clear();self.analysis=self.prepared=self.next_probe=None
            self.input_budget=ResponseBudget(self.session.clock)
            fields=dict(session=session.session,turn=turn,revision=revision)
            await self.send('scope',management_v=1,state='active',**fields)
            if current():
                await self.send('volume',control_v=1,direction='up' if meaning=='volume_up' else 'down',
                                token=uuid4().hex,**fields)
            return
        if meaning == 'management':
            session,epoch,turn,output=self.session,self.epoch,self.session.turn,self.session.output
            def current():
                return (not self.closed and self.session is session and self.epoch==epoch and
                        self.revision==revision and session.turn==turn and session.output==output and
                        session._live() and session.clock()<deadline and
                        not session.management_paused and not self.waiting_wake)
            if not current():return
            self.capture.clear();self.analysis=self.next_probe=self.prepared=None
            self.awaiting_input=False
            fields=dict(session=session.session,turn=turn,revision=revision)
            # A first-turn request has no open/bound. Establish its normal scope
            # before the event; never make the event itself an authority source.
            await self.send('scope',management_v=1,state='active',**fields)
            if not current():return
            await self.send('management',**fields)
            return
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
            stage_timing.mark('compact_skipped',self,operation)
            return
        stage_timing.mark('compact_start',self,operation)
        snapshot = self.session.memory_snapshot(private=self.session.private_mode)
        keep = await self.owned(operation, self.providers.compact, snapshot[-1])
        if epoch != self.epoch:
            raise WireError('stale summary')
        self.session.compact(snapshot, keep)
        stage_timing.mark('compact_end',self,operation)
        if len(self.session.revealed) >= 80:
            # Replays remain rejected by exact pending-front ID and task sequence.
            self.session.revealed.intersection_update(s.name for s in self.session.pending)

    async def review(self, operation, text, *, query='', phase='whole'):
        # Re-project current authoritative scope with this response's input,
        # never a frozen PLAN snapshot or the unapproved candidate sentence.
        operation.ensure()
        stage_timing.mark(phase+'_start',self,operation)
        try:
            function=getattr(self.providers,'review',None) or self.providers.safe
            verdict = await self.owned(operation, function, text, operation.session.context(query=query))
        except SafetyFault:
            stage_timing.mark(phase+'_end',self,operation,outcome='safety_denied')
            raise
        except Exception:
            stage_timing.mark(phase+'_end',self,operation,outcome='failed')
            raise SafetyFault('review_unavailable') from None
        outcome=('safety_denied' if not verdict.safety_allowed else 'quality_denied' if not verdict.quality_allowed else 'ok') if isinstance(verdict,ReviewDecision) else 'ok' if verdict is True else 'safety_denied' if verdict is False else 'failed'
        stage_timing.mark(phase+'_end',self,operation,outcome=outcome)
        if isinstance(verdict,ReviewDecision):
            if not verdict.safety_allowed:raise SafetyFault('content_blocked')
            if not verdict.quality_allowed:raise QualityFault()
        elif verdict is not True:
            # Legacy injected boolean safety providers remain fail-closed.
            raise SafetyFault('content_blocked' if verdict is False else 'review_unavailable')

    def respond(self, text, epoch):
        return self._respond(text, epoch, Operation(self, epoch))

    async def _respond(self, text, epoch, operation):
        owner = asyncio.current_task()
        self.generation_scopes[owner] = operation
        stage = 'bind'
        self.last_guess_normalization=None
        response_revision = self.revision
        fact_prefetch = None
        prefetch_retired = False
        async def prefetch_facts():
            operation.ensure()
            if response_revision != self.revision:raise StaleOperation()
            return await self.read_request(operation, 'facts', text)
        async def retire_prefetch():
            nonlocal prefetch_retired
            if fact_prefetch is None or prefetch_retired or fact_prefetch.done():return True
            prefetch_retired = True
            fact_prefetch.cancel()
            try:
                done, _ = await asyncio.wait({fact_prefetch}, timeout=.3)
            except asyncio.CancelledError:
                self.quarantined = True
                raise
            if not done:self.quarantined = True
            return bool(done)
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
            ending=False
            image_effect=None; answer_public=False
            stage = 'input_policy'
            if getattr(self.policy, 'needs_local_help', lambda _: False)(text) is True:
                raise SafetyFault('content_blocked')
            if hasattr(self.providers, 'plan'):
                context = self.session.context(query=text or '')
                if self.images_enabled and hasattr(self.providers,'image_catalogue'):
                    context['image_catalog']=self.providers.image_catalogue()
                    context['image_controls']=self.dynamic_enabled and self.cache_live(self.visual_cache)
                stage = 'plan'
                # FACTS consumes only this immutable input text, never context.
                # Existing private sessions (including shared re-planning) keep
                # serial extraction; publication remains at the original gate.
                if not self.session.private_mode:
                    fact_prefetch = asyncio.create_task(prefetch_facts())
                    self.track_retired(fact_prefetch)
                plan = await self.read_request(operation, 'plan', text, context)
                self.last_guess_normalization=plan.get('_guess_normalization')
                if epoch != self.epoch or not self.session._output_live():
                    return
                shared_replanned = self.session.private_mode and plan['action'] in {'change', 'leave'}
                if shared_replanned:
                    # Project without changing scope: a failed/cancelled re-plan
                    # must leave the current private session private. Only the
                    # final plan may decide the action and publication scope.
                    plan = await self.read_request(operation, 'plan', text,
                        operation.session.context(shared=True, query=text or ''), allow_plan_repair=False)
                    self.last_guess_normalization=plan.get('_guess_normalization')
                    operation.ensure()
                action = plan['action']
                ending=action=='end'
                if action == 'handoff' and any((self.session.recent, self.session.facts,
                                                         self.session.public, self.session.private,
                                                         self.session.game, self.session.secrets)):
                    if not await retire_prefetch():raise WireError('fact prefetch close timeout')
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
                elif shared_replanned:
                    self.session.private_mode = False
                if action == 'leave':
                    plan.update(mode='chat', rules='', roles=[], secrets={})
                if epoch != self.epoch or not self.session._output_live():
                    return
                stage = 'facts'
                if ending:
                    if not await retire_prefetch():raise WireError('fact prefetch close timeout')
                    facts = []
                elif fact_prefetch is not None:
                    facts = await asyncio.shield(fact_prefetch)
                else:
                    facts = await self.read_request(operation, 'facts', text)
                operation.ensure()
                if response_revision != self.revision:raise StaleOperation()
                if epoch != self.epoch or not self.session._output_live():
                    return
                stage = 'fact_commit'
                accepted=True if ending else self.session.record_input(text, facts)
                stage_timing.mark('fact_commit',self,operation,count=len(facts) if accepted is not False else 0,outcome='failed' if accepted is False else 'ok')
                if accepted is False:
                    # A real storage bound is a normal conversational branch,
                    # not a provider failure or a license to invent recollection.
                    plan.update(sentences=['我这会儿记不全前面的细节，请再告诉我这次最重要的事，我们接着玩。'],anchors={},tools=[])
                    plan.update(mode=self.session.game.get('mode','chat'),
                                rules=self.session.game.get('rules',''),roles=self.session.game.get('roles',[]),
                                secrets=dict(self.session.secrets))
                    if 'guess_role' in self.session.game:plan['guess_role']=self.session.game['guess_role']
                    else:plan.pop('guess_role',None)
                if ending:plan.update(tools=[],anchors={})
                stage = 'safety'
                await self.review(operation, ''.join(plan['sentences']), query=text or '')
                state = {k: plan[k] for k in ('mode', 'rules', 'roles', 'secrets')}
                if plan['mode']=='guess' and 'guess_role' in plan:state['guess_role']=plan['guess_role']
                if state['mode']=='story':
                    if accepted is False and 'turn_limit' in self.session.game:
                        state['turn_limit']=self.session.game['turn_limit']
                    elif accepted is not False and '_story_turn_limit' in plan:
                        state['turn_limit']=plan['_story_turn_limit']
                image_effect=None; answer_public=False
                tools=plan.get('tools',[])
                if self.images_enabled and tools:
                    request=tools[0]
                    if request['kind']=='hide_image':
                        await self.hide_visual('requested')
                    if request['kind'] in {'hide_image','extend_image','reshow_image'}:
                        cache=self.visual_cache
                        current=dict(self.session.game,secrets=dict(self.session.secrets))
                        if (self.dynamic_enabled and self.cache_live(cache) and plan['action']=='continue' and
                            state==current and not plan['anchors']):
                            self.invalidate_visual(keep_cache=True)
                            prepared=dict(session=self.session.session,turn=self.session.turn,
                                revision=response_revision,topic=self.session.topic+1,token=uuid4().hex,
                                epoch=self.epoch,output=self.session.output,ready=None,played=None,answer_asset=None,
                                connection=self.session.connection,player=self.session.player,stream=self.session.stream,
                                control={'extend_image':'extend','reshow_image':'reshow','hide_image':'hide'}[request['kind']],cache=cache,
                                request=request,operation=operation,display_seconds=12 if plan['mode']=='story' else 6)
                            self.prepared_visual=prepared;image_effect='image:'+prepared['token']
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
                                    answer_asset=candidate.asset_id if answer_public else None,
                                    connection=self.session.connection,player=self.session.player,stream=self.session.stream,
                                    dynamic=self.dynamic_enabled and request['kind']=='generate_image',
                                    request=request,operation=operation,display_seconds=12 if plan['mode']=='story' else 6)
                                self.prepared_visual=prepared
                                image_effect='image:'+prepared['token']
                                if not prepared['dynamic']:
                                    self.visual_task=asyncio.create_task(self.prepare_visual(prepared,request,operation))
                if answer_public:
                    state['secrets']={} # proposal only, committed by the final played ACK
                @asynccontextmanager
                async def planned():
                    async def items():
                        nonlocal stage
                        for sentence in plan['sentences']:
                            if len(plan['sentences']) > 1:
                                stage='safety'
                                await self.review(operation, sentence, query=text or '', phase='segment')
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
                    stage_timing.mark('tts_open',self,operation,count=sentence_number)
                    async with self.owned_resource(operation, self.providers.synthesize, approved, 24000) as chunks:
                        stage_timing.mark('tts_ready',self,operation,count=sentence_number)
                        diagnostic_chunks=0
                        # One-chunk lookahead marks the final chunk's public fact.
                        previous = None
                        async for chunk in self.owned_items(operation, chunks):
                            diagnostic_chunks+=1
                            if diagnostic_chunks<=2:stage_timing.mark('tts_first_pcm' if diagnostic_chunks==1 else 'tts_second_pcm',self,operation,count=sentence_number,bytes=len(chunk) if isinstance(chunk,bytes) else 0)
                            if not isinstance(chunk, bytes) or not chunk or len(chunk) % 2 or len(chunk) > 4800:
                                raise WireError('pcm capacity')
                            if previous is not None:
                                await self.audio(previous, '', epoch, operation=operation)
                            previous = chunk
                        stage_timing.mark('tts_eof',self,operation,count=sentence_number)
                        if previous is None:
                            raise WireError('empty synthesis')
                        final_sentence=state is not None and sentence_number==len(plan['sentences'])
                        anchors=tuple(k for k,i in plan['anchors'].items() if i==sentence_number-1) if state is not None else ()
                        if final_sentence and answer_public: anchors=tuple(dict.fromkeys(anchors+('answer.current',)))
                        await self.audio(previous, approved, epoch,
                                         effect=image_effect if final_sentence else None,
                                         state=state if state is not None and sentence_number == len(plan['sentences']) else None,
                                         anchors=anchors, operation=operation)
                    stage_timing.mark('tts_released',self,operation,count=sentence_number)
            while self.session.pending:
                self.changed.clear()
                if epoch != self.epoch or not self.session._output_live():
                    raise WireError('revoked')
                await self.owned(operation, self.changed.wait)
            operation.ensure()
            if ending:
                ended=dict(session=self.session.session,turn=self.session.turn,revision=self.revision)
                self.session.clear()
                self.capture.clear();self.analysis=self.next_probe=self.prepared=None
                self.awaiting_input=False
                self.management_receipt=None;self.management_scope=None;self.management_ready=False
                await self.commands()
                await self.send('session_end',reason='conversation_ended',**ended)
                return
            self.session.deadline = 0
            await self.send('reply_end', head=self.session.head, public_facts=len(self.session.public))
        except StaleOperation:
            return
        except asyncio.CancelledError:
            stage_timing.mark('cancel',self,operation,outcome='cancelled')
            raise
        except Exception as failure:
            if not operation.valid():
                return
            try:self.last_failure = failure_observer.metadata(stage,failure)
            except BaseException:self.last_failure = dict(stage='unknown',kind='unknown',contract='unknown')
            failure_observer.record(self,operation,stage,failure,revision=response_revision)
            # Exception messages may contain provider content/credentials: never emit.
            self.session.interrupt()
            await self.commands()
            if self.session is not operation.session or epoch != self.epoch or self.session.turn != operation.turn:
                return
            # Required facts/context failed closed: no candidate or fabricated
            # evidence may be spoken. Preserve the original last_failure above,
            # but keep fixed local support reachable without another model call.
            # Explicit quota/safety signals retain their existing classifications.
            context_failure = stage in {'facts','fact_commit'} and not (
                isinstance(failure, VoiceFault) and failure.code in {'quota','safety'})
            if context_failure or isinstance(failure, SafetyFault) or isinstance(failure, VoiceFault) and failure.code == 'safety':
                # Stop/revoke first. A newer input/connection cannot borrow this help notification.
                if self.revision != response_revision or self.closed or not self.session._live():
                    return
                # The local help replaces this failed response, not a new cloud retry.
                self.awaiting_input = False
                self.capture.clear()
                self.analysis = self.prepared = self.next_probe = None
                self.input_budget = ResponseBudget(self.session.clock)
                self.session.deadline = 0
                reason = failure.reason if isinstance(failure, SafetyFault) else 'review_unavailable' if context_failure else 'content_blocked'
                await self.send('failure', code='safety', session=operation.session_id,
                                turn=operation.turn, revision=response_revision, local_help=local_help(reason))
            else:
                await self.send('failure', code=failure.code if isinstance(failure, VoiceFault) else 'timeout' if isinstance(failure, TimeoutError) else 'voice')
            if self.quarantined:
                await self.close_quarantined()
        finally:
            try:await retire_prefetch()
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

    async def finish_session_expiry(self, scope):
        session, epoch, revision, connection, turn, output = scope
        def current():
            return (self.session is session and self.epoch == epoch and self.revision == revision
                    and session.connection == connection and session.turn == turn and session.output == output
                    and not session.active and session.expiry_reason == 'session_expired' and not self.closed)
        if not current():return False
        if self.expiry_notice_scope is not None and self.expiry_notice_scope[0] is session:return True
        # Claim before any await; no duplicate terminal event for this dead session.
        self.expiry_notice_scope=scope
        self.capture.clear();self.analysis=self.next_probe=self.prepared=None
        self.awaiting_input=False;self.waiting_wake=False;self.settling_stop=None
        self.management_receipt=None;self.management_scope=None;self.management_ready=False
        self.ack_identity=None
        self.invalidate_visual()
        tasks=set(self.retired_tasks)
        recognition=self.recognition
        try:
            await self.commands()
            if not current():return False
            await self.cancel_generation()
            if not current() or self.generation is not None:return False
            await self.cancel_recognition()
            if not current() or self.recognition is not recognition:return False
            deadline=asyncio.get_running_loop().time()+.5
            while True:
                tasks.update(self.retired_tasks)
                pending={t for t in tasks if not t.done()}
                # Closing tasks must finish, not be cancelled and counted released.
                remaining=deadline-asyncio.get_running_loop().time()
                if pending and remaining>0:await asyncio.wait(pending,timeout=remaining)
                await asyncio.sleep(0)
                if not current():return False
                tasks.update(self.retired_tasks)
                pending={t for t in tasks if not t.done()}
                if not pending:break
                if asyncio.get_running_loop().time()>=deadline:
                    self.quarantined=True
                    break
            if any(t.done() and not t.cancelled() and t.exception() is not None for t in tasks):self.quarantined=True
        except WireError:
            self.quarantined=True
        if not current() or self.generation is not None or self.recognition is not recognition:return False
        if self.quarantined:
            await self.send('failure',code='voice')
            await self.close_quarantined()
        else:
            # Ignore buffered intake that arrived during bounded old-task close.
            self.capture.clear();self.analysis=self.next_probe=self.prepared=None
            self.awaiting_input=False
            self.recognition=None
            self.generation_scopes.clear();self.recognition_scopes.clear()
            await self.send('session_end',reason='session_expired',session=session.session,turn=turn,revision=revision)
        return True

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
            token=self.settling_stop
            current=(self.session,self.epoch,self.revision,self.session.connection,self.session.turn,self.session.output)
            timing=(self.session.deadline,self.session.progress_deadline,self.session.response_confirmed,self.session.response_expired)
            settling=(token is not None and token['scope']==current and token['prepared'] is self.prepared and
                      token['budget'] is self.input_budget and token['budget_deadline']==self.input_budget.deadline and
                      token['timing']==timing and (self.generation is None or self.generation is token['generation']))
            # A live incoming expression/prepared owns its original ingress
            # budget. Never poll the revoked previous reply's deadline for it.
            incoming=(self.awaiting_input and self.input_budget.deadline is not None and
                      self.session.player is None and not self.session.pending and
                      (self.generation is None or token is not None and self.generation is token['generation']) and
                      (self.prepared is None or self.prepared[3]==self.revision and self.prepared[1]==self.input_budget.deadline))
            session,epoch,revision=self.session,self.epoch,self.revision
            if settling or incoming:session._live() # TTL/heartbeat still expire
            else:session.poll()
            expired_scope=(session,epoch,revision,session.connection,session.turn,session.output)
            if not session.active and session.expiry_reason == 'session_expired':
                if await self.finish_session_expiry(expired_scope):return
                continue
            await self.commands()
            await self.poll_visual()
            if not self.session.active or self.session.response_expired:
                await self.cancel_generation()
                await self.send('failure', code='timeout')
                return

    async def run(self):
        monitor = asyncio.create_task(self.monitor())
        receiver = None
        try:
            while not self.closed:
                if not self.session.active:
                    # handle(heartbeat/scope) can discover expiry before monitor.
                    # Let the same scoped monitor emit the terminal event first.
                    if self.session.expiry_reason is not None:await monitor
                    break
                receiver = asyncio.create_task(self.socket.recv())
                done, _ = await asyncio.wait({receiver, monitor}, return_when=asyncio.FIRST_COMPLETED)
                if monitor in done:
                    await monitor
                    break
                await self.handle(receiver.result())
        finally:
            self.closed = True
            self.management_receipt=None;self.management_scope=None;self.management_ready=False;self.waiting_wake=False
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
