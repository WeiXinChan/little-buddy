"""Opt-in one-expression task-local scalar trace. No default records or logging."""
from contextlib import contextmanager
from contextvars import ContextVar
from types import MappingProxyType
import asyncio
import inspect
import time

STAGES=frozenset('asr_finish_sent tts_connected tts_task_ready probe_received seal_received stop_received bind_received ack_received ack_progress effective_ack endpoint_sent decision_sent open_sent bound_sent first_audio_sent reply_end session_end failure cancel asr_open asr_ready asr_final asr_released endpoint_start endpoint_end plan_start plan_end facts_start facts_end fact_commit whole_start whole_end segment_start segment_end compact_start compact_end compact_skipped tts_open tts_ready tts_first_pcm tts_second_pcm tts_eof tts_released'.split())
_current=ContextVar('v2_expression_timing',default=None)

class Trace:
    """A caller explicitly supplies a fresh Trace per expression; never a service log."""
    def __init__(self,observer=None):
        if observer is not None and (not callable(observer) or inspect.iscoroutinefunction(observer)):raise ValueError('observer_sync_required')
        self.started=time.monotonic();self.rows=[];self.truncated=False;self.observer_failed=False
        self.observer=observer;self.peer=None;self.session=None;self.session_id=None;self.connection=None;self.open=True;self.invalid_scope=0;self.audio_seen=False
    def report(self):
        return dict(round=1,records=[dict(r) for r in self.rows],truncated=self.truncated,
                    observer_failed=self.observer_failed,invalid_scope=self.invalid_scope)

def enabled():return _current.get() is not None

@contextmanager
def observe(trace):
    if not isinstance(trace,Trace):raise ValueError('trace_type')
    token=_current.set(trace)
    try:yield trace
    finally:trace.open=False;trace.peer=None;trace.session=None;_current.reset(token)

def mark(stage,peer,operation=None,*,count=0,bytes=0,outcome='ok'):
    trace=_current.get()
    if trace is None or not trace.open:return
    # Diagnostics must not invoke _live()/valid(), mutate session or consume time budgets.
    try:
        if stage not in STAGES or outcome not in {'ok','safety_denied','quality_denied','failed','cancelled'}:return
        if type(count) is not int or type(bytes) is not int or not 0<=count<=2**31-1 or not 0<=bytes<=2**31-1:return
        s=peer.session
        if operation is not None and (operation.peer is not peer or operation.session is not s or operation.session_id!=s.session or operation.connection!=s.connection or operation.turn!=s.turn or operation.epoch!=peer.epoch or operation.revision is not None and operation.revision!=peer.revision or operation.output is not None and operation.output!=s.output or operation.cancelled and stage!='cancel'):
            trace.invalid_scope=min(2**31-1,trace.invalid_scope+1);return
        if operation is not None and s.clock()>=min(s.expires,s.heartbeat_deadline) and stage not in {'cancel','session_end','failure'}:
            trace.invalid_scope=min(2**31-1,trace.invalid_scope+1);return
        if trace.peer is None:
            trace.peer=peer;trace.session=s;trace.session_id=s.session;trace.connection=s.connection
        if trace.peer is not peer or trace.session is not s or trace.session_id!=s.session or trace.connection!=s.connection:
            trace.invalid_scope=min(2**31-1,trace.invalid_scope+1);return
        if peer.closed or (not s.active and stage not in {'session_end','failure','cancel'}):return
        if stage=='first_audio_sent':
            if trace.audio_seen:return
            trace.audio_seen=True
        if len(trace.rows)>=128:trace.truncated=True;return
        row=dict(stage=stage,ms=round(max(0,time.monotonic()-trace.started)*1000,3),round=1,
                 epoch=peer.epoch,revision=peer.revision,turn=s.turn,count=count,bytes=bytes,outcome=outcome)
        trace.rows.append(row)
        if trace.observer is not None:
            try:
                result=trace.observer(MappingProxyType(dict(row)))
                if inspect.isawaitable(result):
                    if inspect.iscoroutine(result):result.close()
                    elif isinstance(result,asyncio.Future):result.cancel()
                    raise ValueError('observer_sync_required')
            except BaseException:
                trace.observer_failed=True;trace.observer=None
    except BaseException:
        # A measurement bug is never a voice failure or an exception-body log.
        trace.observer_failed=True;trace.observer=None

@contextmanager
def provider_marks(peer,operation):
    # Only this explicitly observed V2 resource installs the shared provider port.
    # These are new V2 observations, never imported V1 request records.
    if not enabled():
        yield;return
    from backend.timing import observer
    names={'asr_finish_sent':'asr_finish_sent','tts_socket_ready':'tts_connected','tts_task_ready':'tts_task_ready'}
    def forward(event,segment=0):
        stage=names.get(event)
        if stage:mark(stage,peer,operation)
    token=observer.set(forward)
    try:yield
    finally:observer.reset(token)
